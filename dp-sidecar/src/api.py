"""
Main API for DP Sidecar - Differential Privacy for Fider Voting
Provides endpoints to query DP-protected vote counts.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta

from .config import (
    THRESHOLD, EPSILON_PER_QUERY, WINDOW_TYPE, 
    WINDOW_RESET_TIME, DEMO_MODE, DEMO_WINDOW_SECONDS
)
from .database.connections import get_fider_connection, get_dp_connection, get_true_count_from_fider
from .dp_mechanism import DPMechanism
from .budget_tracker import BudgetTracker

app = FastAPI(
    title="DP Sidecar API",
    description="Differential Privacy layer for Fider voting platform",
    version="1.0.0"
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize DP mechanism and budget tracker
dp_mechanism = DPMechanism()
budget_tracker = BudgetTracker()


# ===== RESPONSE MODELS =====

class DPCountResponse(BaseModel):
    """Response model for DP count queries"""
    post_id: int
    noisy_count: Optional[float]
    epsilon_used: float
    meets_threshold: bool
    message: str
    confidence_interval: Optional[dict] = None
    is_locked: bool = False
    window_id: Optional[int] = None


# ===== WINDOW MANAGEMENT =====

def get_current_window(conn):
    """
    Get or create the current active release window.
    """
    cursor = conn.cursor()
    
    # Check for active window
    cursor.execute("""
        SELECT window_id, end_time
        FROM release_windows
        WHERE status = 'active' AND end_time > NOW()
        ORDER BY start_time DESC
        LIMIT 1
    """)
    
    result = cursor.fetchone()
    
    if result:
        return result['window_id']
    
    # No active window - create new one
    now = datetime.now()
    
    if DEMO_MODE:
        # Demo mode: short windows
        end_time = now + timedelta(seconds=DEMO_WINDOW_SECONDS)
    else:
        # Production: daily windows
        end_time = now + timedelta(hours=24)
    
    cursor.execute("""
        INSERT INTO release_windows (start_time, end_time, status)
        VALUES (%s, %s, 'active')
        RETURNING window_id
    """, (now, end_time))
    
    window_id = cursor.fetchone()['window_id']
    conn.commit()
    
    print(f"Created new window {window_id}: {now} to {end_time}")
    
    return window_id


def store_dp_release(post_id: int, window_id: int, true_count: int, 
                     noisy_count: Optional[float], epsilon_used: float, 
                     meets_threshold: bool, conn):
    """Store a DP release in the database"""
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO dp_releases 
        (post_id, window_id, true_count, noisy_count, epsilon_used, meets_threshold)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (post_id, window_id)
        DO UPDATE SET
            true_count = EXCLUDED.true_count,
            noisy_count = EXCLUDED.noisy_count,
            epsilon_used = epsilon_budget.epsilon_used + EXCLUDED.epsilon_used,
            meets_threshold = EXCLUDED.meets_threshold,
            updated_at = NOW()
    """, (post_id, window_id, true_count, noisy_count, epsilon_used, meets_threshold))
    
    conn.commit()


# ===== API ENDPOINTS =====

@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "DP Sidecar",
        "version": "1.0.0",
        "demo_mode": DEMO_MODE
    }


@app.get("/api/counts/{post_id}", response_model=DPCountResponse, tags=["DP Queries"])
def get_dp_count(post_id: int):
    """
    Get DP-protected count for a post.
    
    Key Privacy Feature:
    - Returns SAME noisy value if vote count hasn't changed
    - Generates NEW noise ONLY when vote count changes
    - This prevents averaging attacks
    
    Args:
        post_id: The Fider post ID
        
    Returns:
        DPCountResponse with noisy count or threshold message
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        
        try:
            # Step 1: Quick check if post is locked
            if budget_tracker.is_locked(post_id):
                # Post is locked - return last known count
                cursor.execute("""
                    SELECT noisy_count, updated_at, window_id
                    FROM dp_releases
                    WHERE post_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (post_id,))
                
                last_release = cursor.fetchone()
                
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=round(last_release['noisy_count'], 1) if last_release else None,
                    epsilon_used=0.0,
                    meets_threshold=True,
                    message="Privacy budget exhausted. Showing last available count.",
                    is_locked=True,
                    window_id=last_release['window_id'] if last_release else None
                )
            
            # Step 2: Get current window
            current_window_id = get_current_window(dp_conn)
            
            # Step 3: Get true count from Fider
            true_count = get_true_count_from_fider(post_id)
            
            # Step 4: Check threshold
            if not dp_mechanism.check_threshold(true_count):
                # Below threshold - check if we've already stored this status
                cursor.execute("""
                    SELECT release_id
                    FROM dp_releases
                    WHERE post_id = %s AND window_id = %s
                """, (post_id, current_window_id))
                
                if not cursor.fetchone():
                    # Store the "below threshold" status for this window
                    store_dp_release(post_id, current_window_id, true_count, 
                                   None, 0.0, False, dp_conn)
                
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=None,
                    epsilon_used=0.0,
                    meets_threshold=False,
                    message=f"Not enough voters (minimum: {THRESHOLD})",
                    window_id=current_window_id
                )
            
            # Step 5: Check if we have existing release for this post in this window
            cursor.execute("""
                SELECT release_id, true_count, noisy_count, epsilon_used
                FROM dp_releases
                WHERE post_id = %s AND window_id = %s
            """, (post_id, current_window_id))
            
            existing = cursor.fetchone()
            
            if existing is None:
                # CASE 1: First query for this post in this window
                # Check budget
                has_budget, remaining = budget_tracker.check_budget(
                    post_id, current_window_id, EPSILON_PER_QUERY
                )
                
                if not has_budget:
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=None,
                        epsilon_used=0.0,
                        meets_threshold=False,
                        message="Privacy budget exhausted",
                        is_locked=True,
                        window_id=current_window_id
                    )
                
                # Generate new noise
                noisy_count = dp_mechanism.add_laplace_noise(true_count)
                
                # Store release
                store_dp_release(post_id, current_window_id, true_count, 
                               noisy_count, EPSILON_PER_QUERY, True, dp_conn)
                
                # Deduct budget
                budget_tracker.deduct_budget(post_id, current_window_id, EPSILON_PER_QUERY)
                
                # Calculate confidence interval
                lower, upper = dp_mechanism.calculate_confidence_interval(noisy_count)
                
                print(f"New release: Post {post_id}, true={true_count}, noisy={noisy_count:.2f}")
                
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=round(max(0, noisy_count), 1),
                    epsilon_used=EPSILON_PER_QUERY,
                    meets_threshold=True,
                    message="New release generated",
                    confidence_interval={"lower": round(lower, 1), "upper": round(upper, 1)},
                    window_id=current_window_id
                )
            
            else:
                stored_true_count = existing['true_count']
                stored_noisy_count = existing['noisy_count']
                
                if stored_true_count == true_count:
                    # CASE 2: NO NEW VOTES
                    # Return same noisy count (CRITICAL FOR PRIVACY!)
                    
                    print(f"Cached: Post {post_id}, noisy={stored_noisy_count:.2f} (no change)")
                    
                    lower, upper = dp_mechanism.calculate_confidence_interval(stored_noisy_count)
                    
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=round(max(0, stored_noisy_count), 1),
                        epsilon_used=0.0,  # No new epsilon used
                        meets_threshold=True,
                        message="Cached (no new votes)",
                        confidence_interval={"lower": round(lower, 1), "upper": round(upper, 1)},
                        window_id=current_window_id
                    )
                
                else:
                    # CASE 3: NEW VOTE DETECTED
                    # Check budget
                    has_budget, remaining = budget_tracker.check_budget(
                        post_id, current_window_id, EPSILON_PER_QUERY
                    )
                    
                    if not has_budget:
                        # Budget exhausted - return last known
                        return DPCountResponse(
                            post_id=post_id,
                            noisy_count=round(max(0, stored_noisy_count), 1),
                            epsilon_used=0.0,
                            meets_threshold=True,
                            message="Privacy budget exhausted. Showing last count.",
                            is_locked=True,
                            window_id=current_window_id
                        )
                    
                    # Regenerate noise with new count
                    noisy_count = dp_mechanism.add_laplace_noise(true_count)
                    
                    # Update release
                    store_dp_release(post_id, current_window_id, true_count, 
                                   noisy_count, EPSILON_PER_QUERY, True, dp_conn)
                    
                    # Deduct budget
                    budget_tracker.deduct_budget(post_id, current_window_id, EPSILON_PER_QUERY)
                    
                    lower, upper = dp_mechanism.calculate_confidence_interval(noisy_count)
                    
                    print(f"Updated: Post {post_id}, {stored_true_count}→{true_count}, noisy={noisy_count:.2f}")
                    
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=round(max(0, noisy_count), 1),
                        epsilon_used=EPSILON_PER_QUERY,
                        meets_threshold=True,
                        message=f"Updated (vote change: {stored_true_count}→{true_count})",
                        confidence_interval={"lower": round(lower, 1), "upper": round(upper, 1)},
                        window_id=current_window_id
                    )
        
        except Exception as e:
            print(f"Error in get_dp_count: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/debug/post/{post_id}", tags=["Debug"])
def debug_post(post_id: int):
    """
    Debug endpoint to see both true and noisy counts.
    ⚠️ REMOVE THIS IN PRODUCTION!
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        
        window_id = get_current_window(dp_conn)
        true_count = get_true_count_from_fider(post_id)
        
        cursor.execute("""
            SELECT true_count, noisy_count, epsilon_used, updated_at, meets_threshold
            FROM dp_releases
            WHERE post_id = %s AND window_id = %s
        """, (post_id, window_id))
        
        release = cursor.fetchone()
        
        return {
            "post_id": post_id,
            "window_id": window_id,
            "current_true_count": true_count,
            "threshold": THRESHOLD,
            "stored_release": {
                "true_count": release['true_count'] if release else None,
                "noisy_count": release['noisy_count'] if release else None,
                "epsilon_used": release['epsilon_used'] if release else None,
                "meets_threshold": release['meets_threshold'] if release else None,
                "updated_at": str(release['updated_at']) if release else None
            } if release else None
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)