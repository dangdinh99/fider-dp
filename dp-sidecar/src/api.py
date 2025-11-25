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
    
    print(f"📅 Created new window {window_id}: {now} to {end_time}")
    
    return window_id


# ===== DRAFT UPDATE LOGIC =====

def _update_draft_release(post_id: int, window_id: int, conn):
    """
    SILENT background helper: Pre-compute noisy count if vote changed.

    New behavior:
    - If true_count did NOT change since last published/draft → do NOTHING.
    - Only create/update a draft when:
        * true_count >= THRESHOLD, and
        * true_count differs from the last known true_count.
    - This means:
        * Noise stays the same across windows if there are no new votes.
        * Epsilon is only spent when the underlying count changes and a draft
          is eventually published.
    """
    cursor = conn.cursor()

    # 1) Get current true count from Fider
    true_count = get_true_count_from_fider(post_id)

    # 2) If below threshold, do nothing (no drafts, no budget)
    if not dp_mechanism.check_threshold(true_count):
        # Optional: debug print
        # print(f"⚪ Post {post_id}: true_count={true_count} below threshold, no draft.")
        return

    # 3) Check if we already have a draft for THIS window
    cursor.execute("""
        SELECT true_count, noisy_count, meets_threshold
        FROM dp_releases
        WHERE post_id = %s AND window_id = %s AND status = 'draft'
    """, (post_id, window_id))
    existing_draft = cursor.fetchone()

    # If draft exists and count unchanged, do nothing
    if existing_draft and existing_draft['true_count'] == true_count:
        # No change in truth → keep existing draft as-is
        return

    # 4) If no draft, check the LAST PUBLISHED release (any window)
    if not existing_draft:
        cursor.execute("""
            SELECT true_count, noisy_count
            FROM dp_releases
            WHERE post_id = %s AND status = 'published'
            ORDER BY window_id DESC
            LIMIT 1
        """, (post_id,))
        last_published = cursor.fetchone()

        # If count hasn't changed from last published, do NOTHING.
        # We will reuse that published value across windows via the API fallback.
        if last_published and last_published['true_count'] == true_count:
            # Optional: debug print to reassure ourselves
            print(f"🟢 Post {post_id}: true_count={true_count} unchanged since last published, "
                  "no new draft created (noise & epsilon unchanged).")
            return

    # 5) At this point:
    #    - Either there was no published value, or
    #    - true_count changed since last published/draft.
    #    → We need a NEW DP value for this window.

    # Check budget for this post+window
    has_budget, remaining = budget_tracker.check_budget(post_id, window_id, EPSILON_PER_QUERY)
    if not has_budget:
        print(f"⚠️ Post {post_id} budget exhausted (remaining: {remaining:.2f}), no draft created.")
        return

    # Generate NEW noise (pre-computed but not visible yet)
    noisy_count = dp_mechanism.add_laplace_noise(true_count)

    # Store/overwrite as DRAFT (status='draft' means not visible to users yet)
    cursor.execute("""
        INSERT INTO dp_releases
        (post_id, window_id, true_count, noisy_count, 
         epsilon_used, meets_threshold, status)
        VALUES (%s, %s, %s, %s, %s, TRUE, 'draft')
        ON CONFLICT (post_id, window_id)
        DO UPDATE SET
            true_count = EXCLUDED.true_count,
            noisy_count = EXCLUDED.noisy_count,
            epsilon_used = EXCLUDED.epsilon_used,
            meets_threshold = TRUE,
            updated_at = NOW()
    """, (post_id, window_id, true_count, noisy_count, EPSILON_PER_QUERY))
    conn.commit()

    change_type = (
        "initial"
        if not existing_draft
        else f"{existing_draft['true_count']}→{true_count}"
    )
    print(f"📝 Draft updated: Post {post_id} ({change_type}), "
          f"true_count={true_count}, noisy={noisy_count:.2f} [NOT PUBLISHED YET]")
    
    # Check budget
    has_budget, remaining = budget_tracker.check_budget(post_id, window_id, EPSILON_PER_QUERY)
    if not has_budget:
        print(f"⚠️ Post {post_id} budget exhausted (remaining: {remaining:.2f})")
        return
    
    # Generate NEW noise (this is pre-computed but not shown yet!)
    noisy_count = dp_mechanism.add_laplace_noise(true_count)
    
    # Store as DRAFT (status='draft' means not visible to users)
    cursor.execute("""
        INSERT INTO dp_releases
        (post_id, window_id, true_count, noisy_count, 
         epsilon_used, meets_threshold, status)
        VALUES (%s, %s, %s, %s, %s, TRUE, 'draft')
        ON CONFLICT (post_id, window_id)
        DO UPDATE SET
            true_count = EXCLUDED.true_count,
            noisy_count = EXCLUDED.noisy_count,
            epsilon_used = dp_releases.epsilon_used + EXCLUDED.epsilon_used,
            meets_threshold = TRUE,
            updated_at = NOW()
    """, (post_id, window_id, true_count, noisy_count, EPSILON_PER_QUERY))
    
    conn.commit()
    
    change_type = "initial" if not existing_draft else f"{existing_draft['true_count']}→{true_count}"
    print(f"📝 Draft updated: Post {post_id} ({change_type}), noisy={noisy_count:.2f} [NOT PUBLISHED YET]")


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
    
    KEY PRIVACY FEATURE:
    - Returns PUBLISHED data from scheduler (prevents timing attacks)
    - Silently updates draft in background (pre-computes noise)
    - Users see data from last window release, not real-time
    
    Args:
        post_id: The Fider post ID
        
    Returns:
        DPCountResponse with published noisy count
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        
        try:
            # Step 1: Get current window
            current_window_id = get_current_window(dp_conn)
            
            # Step 2: Check if post is locked (quick check)
            if budget_tracker.is_locked(post_id):
                # Post is locked - return last published count
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
                        message="Not enough voters (minimum: 15)",
                        is_locked=True,
                        window_id=current_window_id
                    )
            
            # Step 3: Check for PUBLISHED release in current window
            cursor.execute("""
                SELECT noisy_count, meets_threshold, updated_at
                FROM dp_releases
                WHERE post_id = %s AND window_id = %s AND status = 'published'
            """, (post_id, current_window_id))
            
            current_published = cursor.fetchone()
            
            if current_published:
                # We have published data for current window!
                # (This means scheduler already ran for this window)
                
                # Still update draft silently for next window
                _update_draft_release(post_id, current_window_id, dp_conn)
                
                if current_published['meets_threshold']:
                    noisy = current_published['noisy_count']
                    lower, upper = dp_mechanism.calculate_confidence_interval(noisy)
                    
                    return DPCountResponse(
                        post_id=post_id,
                        noisy_count=round(noisy, 1),
                        epsilon_used=0.0,  # Not consuming new budget on read
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
                        message="Not enough voters (minimum: 15)",
                        window_id=current_window_id
                    )
            
            # Step 4: No published data for current window yet
            # This means we're still in the middle of a window
            # Return data from PREVIOUS window (stale but safe!)
            
            # First, update draft for next release (silent)
            _update_draft_release(post_id, current_window_id, dp_conn)
            
            # Get most recent published release
            cursor.execute("""
                SELECT noisy_count, meets_threshold, window_id, updated_at
                FROM dp_releases
                WHERE post_id = %s AND status = 'published'
                ORDER BY window_id DESC
                LIMIT 1
            """, (post_id,))
            
            previous_published = cursor.fetchone()
            
            if previous_published and previous_published['meets_threshold']:
                # Return previous window's data
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
                # No previous data OR previous was below threshold
                return DPCountResponse(
                    post_id=post_id,
                    noisy_count=None,
                    epsilon_used=0.0,
                    meets_threshold=False,
                    message="Not enough voters (minimum: 15)",
                    window_id=current_window_id
                )
        
        except Exception as e:
            print(f"❌ Error in get_dp_count: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/budget/{post_id}", tags=["Admin"])
def get_budget_info(post_id: int):
    """
    Admin endpoint: Check budget status for a post.
    """
    with get_dp_connection() as dp_conn:
        cursor = dp_conn.cursor()
        window_id = get_current_window(dp_conn)
        
        cursor.execute("""
            SELECT epsilon_remaining, monthly_epsilon_cap, is_locked, locked_at
            FROM epsilon_budget
            WHERE post_id = %s AND window_id = %s
        """, (post_id, window_id))
        
        budget = cursor.fetchone()
        
        if not budget:
            return {
                "post_id": post_id,
                "window_id": window_id,
                "epsilon_remaining": None,
                "message": "No budget entry (post not yet queried)"
            }
        
        return {
            "post_id": post_id,
            "window_id": window_id,
            "epsilon_remaining": round(budget['epsilon_remaining'], 2),
            "monthly_epsilon_cap": budget['monthly_epsilon_cap'],
            "is_locked": budget['is_locked'],
            "locked_at": str(budget['locked_at']) if budget['locked_at'] else None,
            "queries_remaining": int(budget['epsilon_remaining'] / EPSILON_PER_QUERY)
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