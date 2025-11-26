"""
Window Scheduler - Publishes draft releases at scheduled times

This module runs background jobs that:
1. Close expired windows
2. Publish all draft releases (mark status='published')
3. Deduct epsilon from budgets
4. Create new windows

KEY: This is what prevents timing attacks!
Users never see real-time changes - only scheduled publications.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from .config import WINDOW_RESET_TIME, DEMO_MODE, DEMO_WINDOW_SECONDS, EPSILON_PER_QUERY
from .database.connections import get_dp_connection
from .budget_tracker import BudgetTracker

budget_tracker = BudgetTracker()

def publish_window_releases():
    """
    Batch scheduler: Reads counts, generates noise, publishes.
    
    KEY BEHAVIOR:
    - Only generates NEW noise when true_count changed since last published
    - If count unchanged → reuses previous noisy_count (no new epsilon!)
    - All logic in one place (no drafts)
    """
    print(f"\n{'='*70}")
    print(f"🕐 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Publishing window releases...")
    print(f"{'='*70}")
    
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        
        # Step 1: Get current active window
        print("DEBUG: Getting active window...")
        cursor.execute("""
            SELECT window_id, start_time, end_time
            FROM release_windows
            WHERE status = 'active'
            ORDER BY window_id DESC
            LIMIT 1
        """)
        
        current_window = cursor.fetchone()
        
        if not current_window:
            print("⚠️ No active window found - creating one")
            _create_new_window(conn)
            return
        
        window_id = current_window['window_id']
        start_time = current_window['start_time']
        end_time = current_window['end_time']
        
        print(f"📅 Processing window {window_id}")
        print(f"   Period: {start_time} to {end_time}")
        
        # Step 2: Get posts (just use tracked posts)
        print("DEBUG: Getting tracked posts...")
        cursor.execute("""
            SELECT DISTINCT post_id
            FROM dp_releases
        """)
        active_posts = cursor.fetchall()
        
        print(f"DEBUG: Found {len(active_posts)} tracked posts")
        
        if not active_posts:
            print("   No tracked posts found")
        else:
            print(f"   Found {len(active_posts)} posts to process")
        
        published_count = 0
        reused_count = 0
        locked_count = 0
        below_threshold_count = 0
        
        # Step 3: Import dependencies inside function
        from .database.connections import get_true_count_from_fider
        from .dp_mechanism import DPMechanism
        
        dp_mechanism = DPMechanism()
        
        # Step 4: Process each post
        print("DEBUG: Starting post loop...")
        for idx, post_row in enumerate(active_posts):
            post_id = post_row['post_id']
            print(f"DEBUG: Processing post {idx+1}/{len(active_posts)}: post_id={post_id}")
            
            try:
                # Get current true count
                print(f"DEBUG:   Getting true count for post {post_id}...")
                true_count = get_true_count_from_fider(post_id)
                print(f"DEBUG:   True count: {true_count}")
                
                # Check threshold
                if not dp_mechanism.check_threshold(true_count):
                    print(f"DEBUG:   Below threshold, skipping")
                    below_threshold_count += 1
                    continue
                
                # Get last published
                print(f"DEBUG:   Getting last published...")
                cursor.execute("""
                    SELECT true_count, noisy_count
                    FROM dp_releases
                    WHERE post_id = %s AND status = 'published'
                    ORDER BY window_id DESC
                    LIMIT 1
                """, (post_id,))
                
                last_published = cursor.fetchone()
                print(f"DEBUG:   Last published: {last_published}")
                
                # Check if count unchanged
                if last_published and last_published['true_count'] == true_count:
                    print(f"DEBUG:   Count unchanged, reusing...")
                    previous_noisy = last_published['noisy_count']
                    
                    # Store with ZERO epsilon
                    cursor.execute("""
                        INSERT INTO dp_releases
                        (post_id, window_id, true_count, noisy_count, 
                         epsilon_used, meets_threshold, status)
                        VALUES (%s, %s, %s, %s, 0.0, TRUE, 'published')
                        ON CONFLICT (post_id, window_id)
                        DO UPDATE SET 
                            noisy_count = EXCLUDED.noisy_count, 
                            status = 'published',
                            updated_at = NOW()
                    """, (post_id, window_id, true_count, previous_noisy))
                    
                    reused_count += 1
                    print(f"   📌 Post {post_id}: {previous_noisy:.2f} (reused, ε=0.0)")
                    continue
                
                # Count changed - need new noise!
                print(f"DEBUG:   Count changed, generating new noise...")
                noisy_count = dp_mechanism.add_laplace_noise(true_count)
                print(f"DEBUG:   Noisy count: {noisy_count:.2f}")
                
                # Check budget (also initializes if needed)
                print(f"DEBUG:   Checking budget...")
                has_budget, remaining = budget_tracker.check_budget(
                    post_id, window_id, EPSILON_PER_QUERY
                )
                
                if not has_budget:
                    print(f"   🔒 Post {post_id}: Budget exhausted (remaining: {remaining:.2f})")
                    locked_count += 1
                    continue
                
                # Store as published
                print(f"DEBUG:   Storing release...")
                cursor.execute("""
                    INSERT INTO dp_releases
                    (post_id, window_id, true_count, noisy_count, 
                     epsilon_used, meets_threshold, status)
                    VALUES (%s, %s, %s, %s, %s, TRUE, 'published')
                    ON CONFLICT (post_id, window_id)
                    DO UPDATE SET
                        true_count = EXCLUDED.true_count,
                        noisy_count = EXCLUDED.noisy_count,
                        epsilon_used = EXCLUDED.epsilon_used,
                        status = 'published',
                        updated_at = NOW()
                """, (post_id, window_id, true_count, noisy_count, EPSILON_PER_QUERY))
                
                # Deduct budget
                print(f"DEBUG:   Deducting budget...")
                budget_tracker.deduct_budget(post_id, window_id, EPSILON_PER_QUERY, conn)
                
                # Success - increment counter
                published_count += 1
                change_type = "new" if not last_published else f"{last_published['true_count']}→{true_count}"
                print(f"   ✅ Post {post_id}: {noisy_count:.2f} ({change_type}, ε=0.5)")
                
            except Exception as e:
                print(f"   ❌ Post {post_id}: ERROR - {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print("DEBUG: Post loop completed")
        
        # Commit all changes
        conn.commit()
        print("DEBUG: Committed changes")
        
        # Step 5: Close current window
        cursor.execute("""
            UPDATE release_windows SET status = 'closed' WHERE window_id = %s
        """, (window_id,))
        conn.commit()
        print("DEBUG: Closed window")
        
        # Step 6: Summary
        print(f"\n📊 Summary:")
        print(f"   New releases: {published_count}")
        print(f"   Reused (no change): {reused_count}")
        if below_threshold_count > 0:
            print(f"   Below threshold: {below_threshold_count}")
        if locked_count > 0:
            print(f"   🔒 Locked: {locked_count}")
        
        # Step 7: Create new window
        new_window_id = _create_new_window(conn)
        print(f"✅ Done! New window: {new_window_id}")
        print(f"{'='*70}\n")


def _create_new_window(conn):
    """
    Helper: Create a new release window.
    
    Returns:
        window_id of the newly created window
    """
    cursor = conn.cursor()
    now = datetime.now()
    
    if DEMO_MODE:
        # Demo: 30-second windows
        end_time = now + timedelta(seconds=DEMO_WINDOW_SECONDS)
        duration = f"{DEMO_WINDOW_SECONDS}s"
    else:
        # Production: 24-hour windows
        end_time = now + timedelta(days=1)
        duration = "24h"
    
    cursor.execute("""
        INSERT INTO release_windows (start_time, end_time, status)
        VALUES (%s, %s, 'active')
        RETURNING window_id
    """, (now, end_time))
    
    new_window = cursor.fetchone()
    conn.commit()
    
    window_id = new_window['window_id']
    print(f"🆕 Created window {window_id}: {now.strftime('%H:%M:%S')} → {end_time.strftime('%H:%M:%S')} ({duration})")
    
    return window_id


def cleanup_old_windows():
    """
    Maintenance job: Clean up very old windows (optional).
    Keeps database from growing indefinitely.
    """
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        
        # Delete windows older than 90 days
        cursor.execute("""
            DELETE FROM release_windows
            WHERE end_time < NOW() - INTERVAL '90 days'
              AND status = 'closed'
        """)
        
        deleted = cursor.rowcount
        conn.commit()
        
        if deleted > 0:
            print(f"🧹 Cleaned up {deleted} old windows (>90 days)")


def start_scheduler():
    """
    Start the background scheduler.
    
    This is called on API startup (@app.on_event("startup")).
    """
    scheduler = BackgroundScheduler()
    
    if DEMO_MODE:
        # DEMO MODE: Publish every 30 seconds for testing
        scheduler.add_job(
            publish_window_releases,
            'interval',
            seconds=DEMO_WINDOW_SECONDS,
            id='demo_publisher',
            max_instances=1  # Prevent overlapping runs
        )
        print(f"🚀 Scheduler started (DEMO MODE: every {DEMO_WINDOW_SECONDS}s)")
    else:
        # PRODUCTION: Publish at midnight daily
        hour, minute = map(int, WINDOW_RESET_TIME.split(':'))
        scheduler.add_job(
            publish_window_releases,
            'cron',
            hour=hour,
            minute=minute,
            id='daily_publisher',
            max_instances=1
        )
        print(f"🚀 Scheduler started (Daily at {WINDOW_RESET_TIME})")
        
        # Also run cleanup weekly (Sunday at 3 AM)
        scheduler.add_job(
            cleanup_old_windows,
            'cron',
            day_of_week='sun',
            hour=3,
            minute=0,
            id='weekly_cleanup'
        )
    
    scheduler.start()
    return scheduler


# For testing: Run manually
if __name__ == "__main__":
    print("Running manual window publication...")
    publish_window_releases()