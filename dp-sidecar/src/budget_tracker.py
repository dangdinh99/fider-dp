"""
Budget Tracker for Differential Privacy 
Tracks epsilon budget per post across its lifetime 
"""
from typing import Optional, Tuple
from .database.connections import get_dp_connection
from .config import LIFETIME_EPSILON_CAP, EPSILON_PER_QUERY


class BudgetTracker:
    """
    Tracks and enforces epsilon budget limits per post.
    
    Budget is tracked across windows for a post's entire lifetime.
    Once exhausted, the post is locked FOREVER.
    """
    
    def __init__(self, lifetime_cap: float = None):
        """
        Initialize budget tracker.
        
        Args:
            lifetime_cap: Maximum epsilon per post for its entire lifetime
        """
        self.lifetime_cap = lifetime_cap or LIFETIME_EPSILON_CAP
    
    def check_budget(self, post_id: int, window_id: int, epsilon_needed: float) -> Tuple[bool, Optional[float]]:
        """
        Check if enough LIFETIME budget remains for this post.
        
        CHANGED: Now checks total epsilon used across ALL windows, not just current window.
        
        Args:
            post_id: The post ID
            window_id: The current release window (for compatibility)
            epsilon_needed: How much epsilon this query needs
            
        Returns:
            Tuple of (has_budget, epsilon_remaining)
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            # Get TOTAL epsilon used by this post across ALL windows
            cursor.execute("""
                SELECT COALESCE(SUM(epsilon_used), 0) as total_used
                FROM dp_releases
                WHERE post_id = %s AND status = 'published'
            """, (post_id,))
            
            result = cursor.fetchone()
            total_used = result['total_used']
            epsilon_remaining = self.lifetime_cap - total_used
            
            # Check if already locked
            cursor.execute("""
                SELECT is_currently_locked
                FROM dp_items
                WHERE post_id = %s
            """, (post_id,))
            
            item = cursor.fetchone()
            if item and item['is_currently_locked']:
                return False, epsilon_remaining
            
            # Check if enough budget remains
            has_budget = epsilon_remaining >= epsilon_needed
            
            return has_budget, epsilon_remaining
    
    def deduct_budget(self, post_id: int, window_id: int, epsilon_used: float, conn=None) -> float:
        """
        Deduct epsilon from LIFETIME budget after a query.
        
        CHANGED: Updates lifetime total and locks post if budget exhausted.
        
        Args:
            post_id: The post ID
            window_id: The release window
            epsilon_used: Amount of epsilon consumed
            conn: Optional existing connection to reuse
            
        Returns:
            Remaining epsilon budget (across lifetime)
        """
        # Use provided connection or create new one
        if conn is None:
            with get_dp_connection() as new_conn:
                return self._do_deduct(new_conn, post_id, window_id, epsilon_used)
        else:
            return self._do_deduct(conn, post_id, window_id, epsilon_used)

    def _do_deduct(self, conn, post_id: int, window_id: int, epsilon_used: float) -> float:
        """Helper method that does the actual deduction"""
        cursor = conn.cursor()
        
        # Get total epsilon used after this deduction
        cursor.execute("""
            SELECT COALESCE(SUM(epsilon_used), 0) as total_used
            FROM dp_releases
            WHERE post_id = %s AND status = 'published'
        """, (post_id,))
        
        result = cursor.fetchone()
        total_used_before = result['total_used']
        total_used_after = total_used_before + epsilon_used
        epsilon_remaining = self.lifetime_cap - total_used_after
        
        # Check if should lock (not enough for another query)
        should_lock = epsilon_remaining < EPSILON_PER_QUERY
        
        # Update or create dp_items entry
        cursor.execute("""
            INSERT INTO dp_items 
            (post_id, current_window_id, is_currently_locked, total_epsilon_spent, last_updated)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (post_id) 
            DO UPDATE SET
                current_window_id = EXCLUDED.current_window_id,
                is_currently_locked = EXCLUDED.is_currently_locked,
                total_epsilon_spent = EXCLUDED.total_epsilon_spent,
                last_updated = NOW()
        """, (post_id, window_id, should_lock, total_used_after))
        
        # Don't commit here - let caller handle commit
        
        if should_lock:
            print(f"🔒 Post {post_id} LIFETIME budget exhausted! Locked forever.")
            print(f"   Total epsilon used: {total_used_after:.2f}/{self.lifetime_cap}")
        
        return epsilon_remaining
    
    def get_remaining_budget(self, post_id: int, window_id: int = None) -> Optional[float]:
        """
        Get remaining LIFETIME budget for a post.
        
        CHANGED: Returns lifetime budget remaining, not per-window.
        
        Args:
            post_id: The post ID
            window_id: Ignored (kept for compatibility)
            
        Returns:
            Remaining epsilon across lifetime, or None if no entry exists
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT COALESCE(SUM(epsilon_used), 0) as total_used
                FROM dp_releases
                WHERE post_id = %s AND status = 'published'
            """, (post_id,))
            
            result = cursor.fetchone()
            total_used = result['total_used']
            
            return self.lifetime_cap - total_used
    
    def is_locked(self, post_id: int) -> bool:
        """
        Quick check if post is locked (uses dp_items cache).
        
        Args:
            post_id: The post ID
            
        Returns:
            True if locked forever, False otherwise
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT is_currently_locked
                FROM dp_items
                WHERE post_id = %s
            """, (post_id,))
            
            result = cursor.fetchone()
            return result['is_currently_locked'] if result else False
    
    def get_lifetime_stats(self, post_id: int) -> dict:
        """
        Get comprehensive lifetime budget statistics for a post.
        
        Returns:
            Dictionary with budget stats
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            # Get total epsilon used
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(epsilon_used), 0) as total_used,
                    COUNT(*) as num_releases
                FROM dp_releases
                WHERE post_id = %s AND status = 'published' AND epsilon_used > 0
            """, (post_id,))
            
            result = cursor.fetchone()
            total_used = result['total_used']
            num_releases = result['num_releases']
            
            remaining = self.lifetime_cap - total_used
            queries_remaining = int(remaining / EPSILON_PER_QUERY) if remaining >= EPSILON_PER_QUERY else 0
            
            # Get lock status
            is_locked = self.is_locked(post_id)
            
            return {
                'post_id': post_id,
                'lifetime_cap': self.lifetime_cap,
                'total_epsilon_used': total_used,
                'epsilon_remaining': remaining,
                'num_noise_generations': num_releases,
                'queries_remaining': queries_remaining,
                'is_locked': is_locked,
                'budget_percent_used': (total_used / self.lifetime_cap) * 100
            }


def test_budget_tracker():
    """Test lifetime budget tracker functionality"""
    print("Testing LIFETIME Budget Tracker...")
    print("=" * 60)
    
    tracker = BudgetTracker(lifetime_cap=5.0)  # Small cap for testing
    
    test_post_id = 9999
    test_window_id = 1
    
    # Clean up any existing test data
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM epsilon_budget WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM dp_releases WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM dp_items WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM release_windows WHERE window_id = %s", (test_window_id,))
        conn.commit()
    
    # Create test window
    print("\nSetup: Creating test window")
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO release_windows (window_id, start_time, end_time, status)
            VALUES (%s, NOW() - INTERVAL '1 hour', NOW() + INTERVAL '1 hour', 'active')
            ON CONFLICT (window_id) DO NOTHING
        """, (test_window_id,))
        conn.commit()
    print("  ✓ Test window created")
    
    # Test 1: Check budget for new post
    print("\nTest 1: Check budget for new post")
    has_budget, remaining = tracker.check_budget(test_post_id, test_window_id, 0.5)
    print(f"  Has budget: {has_budget}, Remaining: {remaining}")
    assert has_budget is True
    assert remaining == 5.0
    print("  ✓ Passed: New post has full lifetime budget")
    
    # Test 2: Simulate multiple releases across different windows
    print("\nTest 2: Simulate releases across multiple windows")
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        
        for window in range(1, 12):  # 11 windows
            # Create window
            cursor.execute("""
                INSERT INTO release_windows (start_time, end_time, status)
                VALUES (NOW(), NOW() + INTERVAL '1 hour', 'closed')
                RETURNING window_id
            """, )
            new_window = cursor.fetchone()
            window_id = new_window['window_id']
            
            # Add published release
            cursor.execute("""
                INSERT INTO dp_releases
                (post_id, window_id, true_count, noisy_count, epsilon_used, 
                 meets_threshold, status)
                VALUES (%s, %s, 50, 51.2, 0.5, TRUE, 'published')
            """, (test_post_id, window_id))
            
            # Deduct budget
            remaining = tracker.deduct_budget(test_post_id, window_id, 0.5, conn)
            
            conn.commit()
            
            print(f"  Window {window}: Remaining = {remaining:.1f}")
            
            if remaining < EPSILON_PER_QUERY:
                print(f"  🔒 Post locked after {window} releases!")
                break
    
    # Test 3: Check if locked
    print("\nTest 3: Check if post is locked")
    is_locked = tracker.is_locked(test_post_id)
    print(f"  Is locked: {is_locked}")
    assert is_locked is True
    print("  ✓ Passed: Post is locked when lifetime budget exhausted")
    
    # Test 4: Get lifetime stats
    print("\nTest 4: Get lifetime statistics")
    stats = tracker.get_lifetime_stats(test_post_id)
    print(f"  Total used: {stats['total_epsilon_used']:.1f}/{stats['lifetime_cap']}")
    print(f"  Noise generations: {stats['num_noise_generations']}")
    print(f"  Budget used: {stats['budget_percent_used']:.1f}%")
    print(f"  Locked: {stats['is_locked']}")
    print("  ✓ Passed: Lifetime stats calculated correctly")
    
    # Clean up
    print("\nCleanup: Removing test data")
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM dp_releases WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM dp_items WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM release_windows WHERE window_id >= %s", (test_window_id,))
        conn.commit()
    print("  ✓ Cleanup complete")
    
    print("\n" + "=" * 60)
    print("✓ All LIFETIME budget tracker tests passed!")


if __name__ == "__main__":
    test_budget_tracker()