"""
Main API for DP Sidecar - Differential Privacy for Fider Voting
Provides endpoints to query DP-protected vote counts.

KEY DESIGN:
1. API queries trigger silent draft updates (pre-compute noise)
2. Users only see PUBLISHED releases (from previous scheduler run)
3. Scheduler runs at midnight to publish drafts
4. Prevents timing attacks while maintaining fresh noise
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
    version="2.0.0"
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
    is_stale: bool = False
    window_id: Optional[int] = None
    last_updated: Optional[str] = None


# ===== WINDOW MANAGEMENT =====

def get_current_window(conn):
    """
    Get the current active release window.
    
    IMPORTANT: Does NOT create new windows!
    Only the scheduler should create windows.
    
    Returns:
        window_id of current active window, or None if no active window
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
    
    # No active window found
    # Return the most recent closed window instead
    cursor.execute("""
        SELECT window_id
        FROM release_windows
        WHERE status = 'closed'
        ORDER BY window_id DESC
        LIMIT 1
    """)
    
    result = cursor.fetchone()
    
    if result:
        return result['window_id']
    
    # No windows at all - this should only happen on very first startup
    # Return None and let the scheduler create the first window
    return None



# ===== API ENDPOINTS =====

@app.get("/", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "DP Sidecar",
        "version": "2.0.0",
        "demo_mode": DEMO_MODE
    }


@app.get("/api/counts/{post_id}", response_model=DPCountResponse, tags=["DP Queries"])
def get_dp_count(post_id: int):
    """
    Get DP-protected count for a post.
    
    FIXED: Now tracks new posts so scheduler can process them!
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        
        try:
            # Step 1: Get current window
            current_window_id = get_current_window(dp_conn)
            
            if current_window_id is None:
                # No windows yet - wait for scheduler to create first one
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=None,
                    epsilon_used=0.0,
                    meets_threshold=False,
                    message="System initializing. Please wait for first scheduler run.",
                    window_id=None
                )
            
            # Step 2: Check if this post has EVER been tracked
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM dp_releases
                WHERE post_id = %s
            """, (post_id,))
            
            has_any_releases = cursor.fetchone()['count'] > 0
            
            # Step 3: If post is NEW, add initial tracking entry
            if not has_any_releases:
                print(f"📝 New post detected: {post_id} - Adding to tracking")
                
                # Get true count from Fider
                true_count = get_true_count_from_fider(post_id)
                
                # Check if meets threshold
                meets_threshold = dp_mechanism.check_threshold(true_count)
                
                if meets_threshold:
                    # Add initial entry for scheduler to find
                    # Mark as 'draft' - scheduler will publish it
                    cursor.execute("""
                        INSERT INTO dp_releases
                        (post_id, window_id, true_count, noisy_count, 
                         epsilon_used, meets_threshold, status)
                        VALUES (%s, %s, %s, NULL, 0.0, TRUE, 'draft')
                        ON CONFLICT (post_id, window_id) DO NOTHING
                    """, (post_id, current_window_id, true_count))
                    
                    dp_conn.commit()
                    
                    print(f"✓ Post {post_id} added to tracking (true_count={true_count})")
                    print(f"  Scheduler will publish it on next run (~30s)")
                    
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=None,
                        epsilon_used=0.0,
                        meets_threshold=True,
                        message="Post added to tracking. Noisy count will be available after next scheduler run (~30 seconds).",
                        window_id=current_window_id
                    )
                else:
                    # Below threshold - still track it but don't publish
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=None,
                        epsilon_used=0.0,
                        meets_threshold=False,
                        message=f"Not enough voters (minimum: {dp_mechanism.threshold})",
                        window_id=current_window_id
                    )
            
            # Step 4: Post is already tracked - check if locked
            if budget_tracker.is_locked(post_id):
                cursor.execute("""
                    SELECT noisy_count, updated_at, window_id, meets_threshold
                    FROM dp_releases
                    WHERE post_id = %s AND status = 'published'
                    ORDER BY window_id DESC
                    LIMIT 1
                """, (post_id,))
                
                last_release = cursor.fetchone()
                
                if last_release and last_release['meets_threshold']:
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=round(last_release['noisy_count'], 1),
                        epsilon_used=0.0,
                        meets_threshold=True,
                        message="Privacy budget exhausted. Showing last available count.",
                        is_locked=True,
                        window_id=last_release['window_id'],
                        last_updated=str(last_release['updated_at'])
                    )
                else:
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=None,
                        epsilon_used=0.0,
                        meets_threshold=False,
                        message=f"Not enough voters (minimum: {dp_mechanism.threshold})",
                        is_locked=True,
                        window_id=current_window_id
                    )
            
            # Step 5: Check for PUBLISHED release in current window
            cursor.execute("""
                SELECT noisy_count, meets_threshold, updated_at
                FROM dp_releases
                WHERE post_id = %s AND window_id = %s AND status = 'published'
            """, (post_id, current_window_id))
            
            current_published = cursor.fetchone()
            
            if current_published:
                if current_published['meets_threshold']:
                    noisy = current_published['noisy_count']
                    lower, upper = dp_mechanism.calculate_confidence_interval(noisy)
                    
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=round(noisy, 1),
                        epsilon_used=0.0,
                        meets_threshold=True,
                        message="Current window release",
                        confidence_interval={"lower": round(lower, 1), "upper": round(upper, 1)},
                        window_id=current_window_id,
                        last_updated=str(current_published['updated_at'])
                    )
                else:
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=None,
                        epsilon_used=0.0,
                        meets_threshold=False,
                        message=f"Not enough voters (minimum: {dp_mechanism.threshold})",
                        window_id=current_window_id
                    )
            
            # Step 6: No published data for current window - return previous window data
            cursor.execute("""
                SELECT noisy_count, meets_threshold, window_id, updated_at
                FROM dp_releases
                WHERE post_id = %s AND status = 'published'
                ORDER BY window_id DESC
                LIMIT 1
            """, (post_id,))
            
            previous_published = cursor.fetchone()
            
            if previous_published and previous_published['meets_threshold']:
                noisy = previous_published['noisy_count']
                lower, upper = dp_mechanism.calculate_confidence_interval(noisy)
                
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=round(noisy, 1),
                    epsilon_used=0.0,
                    meets_threshold=True,
                    message="Showing previous window data (new release pending)",
                    confidence_interval={"lower": round(lower, 1), "upper": round(upper, 1)},
                    is_stale=True,
                    window_id=previous_published['window_id'],
                    last_updated=str(previous_published['updated_at'])
                )
            else:
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=None,
                    epsilon_used=0.0,
                    meets_threshold=False,
                    message=f"Not enough voters (minimum: {dp_mechanism.threshold})",
                    window_id=current_window_id
                )
        
        except Exception as e:
            print(f"❌ Error in get_dp_count: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/budget/{post_id}", tags=["Admin"])
def get_budget_info(post_id: int):
    """
    Admin endpoint: Check LIFETIME budget status for a post.
    
    CHANGED: Now shows lifetime budget across all windows.
    """
    # Get comprehensive lifetime stats
    stats = budget_tracker.get_lifetime_stats(post_id)
    
    return {
        "post_id": stats['post_id'],
        "lifetime_cap": stats['lifetime_cap'],
        "total_epsilon_used": round(stats['total_epsilon_used'], 2),
        "epsilon_remaining": round(stats['epsilon_remaining'], 2),
        "budget_percent_used": round(stats['budget_percent_used'], 1),
        "num_noise_generations": stats['num_noise_generations'],
        "queries_remaining": stats['queries_remaining'],
        "is_locked": stats['is_locked'],
        "message": "LOCKED FOREVER - Final result" if stats['is_locked'] else "Active"
    }


@app.get("/api/debug/post/{post_id}", tags=["Debug"])
def debug_post(post_id: int):
    """
    Debug endpoint: See both true and noisy counts.
    ⚠️ REMOVE THIS IN PRODUCTION!
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        
        window_id = get_current_window(dp_conn)
        true_count = get_true_count_from_fider(post_id)
        
        # Get draft
        cursor.execute("""
            SELECT true_count, noisy_count, epsilon_used, meets_threshold, status, updated_at
            FROM dp_releases
            WHERE post_id = %s AND window_id = %s AND status = 'draft'
        """, (post_id, window_id))
        draft = cursor.fetchone()
        
        # Get published
        cursor.execute("""
            SELECT true_count, noisy_count, epsilon_used, meets_threshold, status, updated_at
            FROM dp_releases
            WHERE post_id = %s AND window_id = %s AND status = 'published'
        """, (post_id, window_id))
        published = cursor.fetchone()
        
        return {
            "post_id": post_id,
            "window_id": window_id,
            "current_true_count_from_fider": true_count,
            "threshold": THRESHOLD,
            "draft_release": {
                "true_count": draft['true_count'] if draft else None,
                "noisy_count": draft['noisy_count'] if draft else None,
                "epsilon_used": draft['epsilon_used'] if draft else None,
                "meets_threshold": draft['meets_threshold'] if draft else None,
                "updated_at": str(draft['updated_at']) if draft else None
            } if draft else None,
            "published_release": {
                "true_count": published['true_count'] if published else None,
                "noisy_count": published['noisy_count'] if published else None,
                "epsilon_used": published['epsilon_used'] if published else None,
                "meets_threshold": published['meets_threshold'] if published else None,
                "updated_at": str(published['updated_at']) if published else None
            } if published else None
        }


# ===== STARTUP =====

@app.on_event("startup")
async def startup_event():
    """Initialize scheduler on startup"""
    from .window_scheduler import start_scheduler
    start_scheduler()
    print("✅ DP Sidecar API started")
    print(f"   Mode: {'DEMO' if DEMO_MODE else 'PRODUCTION'}")
    print(f"   Threshold: {THRESHOLD} votes")
    print(f"   Epsilon per query: {EPSILON_PER_QUERY}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api:app", host="0.0.0.0", port=8000, reload=True)