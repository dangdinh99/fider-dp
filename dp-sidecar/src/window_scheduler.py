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
    Main scheduled job: Publish all draft releases.
    
    This runs at window boundaries (midnight in production, every 30s in demo).
    It makes pre-computed noisy counts visible to users.
    """
    print(f"\n{'='*70}")
    print(f"🕐 [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Publishing window releases...")
    print(f"{'='*70}")
    
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        
        # Step 1: Get current active window
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
        
        # Step 2: Get all draft releases for this window
        cursor.execute("""
            SELECT post_id, true_count, noisy_count, epsilon_used, meets_threshold
            FROM dp_releases
            WHERE window_id = %s AND status = 'draft'
            ORDER BY post_id
        """, (window_id,))
        
        drafts = cursor.fetchall()
        
        if not drafts:
            print("   No drafts to publish")
        else:
            print(f"   Found {len(drafts)} drafts to publish:")
        
        published_count = 0
        locked_count = 0
        
        # Step 3: Publish each draft
        for draft in drafts:
            post_id = draft['post_id']
            epsilon = draft['epsilon_used']
            noisy = draft['noisy_count']
            meets_threshold = draft['meets_threshold']
            
            try:
                # Deduct epsilon budget NOW (when actually publishing)
                if epsilon > 0:
                    remaining = budget_tracker.deduct_budget(post_id, window_id, epsilon)
                    
                    if remaining < EPSILON_PER_QUERY:
                        locked_count += 1
                        status_icon = "🔒"
                    else:
                        status_icon = "✅"
                else:
                    status_icon = "⬇️"  # Below threshold
                
                # Mark draft as published
                cursor.execute("""
                    UPDATE dp_releases
                    SET status = 'published'
                    WHERE post_id = %s AND window_id = %s AND status = 'draft'
                """, (post_id, window_id))
                
                published_count += 1
                
                if meets_threshold:
                    print(f"   {status_icon} Post {post_id:4d}: {noisy:6.2f} (ε={epsilon:.1f})")
                else:
                    print(f"   {status_icon} Post {post_id:4d}: Below threshold")
                
            except Exception as e:
                print(f"   ❌ Post {post_id}: Error - {e}")
                continue
        
        conn.commit()
        
        # Step 4: Close current window
        cursor.execute("""
            UPDATE release_windows
            SET status = 'closed'
            WHERE window_id = %s
        """, (window_id,))
        conn.commit()
        
        print(f"\n📊 Summary:")
        print(f"   Published: {published_count} releases")
        if locked_count > 0:
            print(f"   🔒 Locked: {locked_count} posts (budget exhausted)")
        
        # Step 5: Create new window
        new_window_id = _create_new_window(conn)
        
        print(f"✅ Window {window_id} closed, new window {new_window_id} created")
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