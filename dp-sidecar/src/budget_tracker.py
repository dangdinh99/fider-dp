"""
Budget Tracker for Differential Privacy
Tracks epsilon budget per post per window and handles locking
"""
from typing import Optional, Tuple
from .database.connections import get_dp_connection
from .config import MONTHLY_EPSILON_CAP, EPSILON_PER_QUERY


class BudgetTracker:
    """
    Tracks and enforces epsilon budget limits per post per window.
    """
    
    def __init__(self, monthly_cap: float = None):
        """
        Initialize budget tracker.
        
        Args:
            monthly_cap: Maximum epsilon per post per month
        """
        self.monthly_cap = monthly_cap or MONTHLY_EPSILON_CAP
    
    def check_budget(self, post_id: int, window_id: int, epsilon_needed: float) -> Tuple[bool, Optional[float]]:
        """
        Check if enough budget remains for this query.
        
        Args:
            post_id: The post ID
            window_id: The current release window
            epsilon_needed: How much epsilon this query needs
            
        Returns:
            Tuple of (has_budget, epsilon_remaining)
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            # Check if budget entry exists
            cursor.execute("""
                SELECT epsilon_remaining, is_locked
                FROM epsilon_budget
                WHERE post_id = %s AND window_id = %s
            """, (post_id, window_id))
            
            result = cursor.fetchone()
            
            if result is None:
                # No entry yet - initialize budget
                self._initialize_budget(post_id, window_id, conn)
                return epsilon_needed <= self.monthly_cap, self.monthly_cap
            
            epsilon_remaining = result['epsilon_remaining']
            is_locked = result['is_locked']
            
            # Check if already locked
            if is_locked:
                return False, epsilon_remaining
            
            # Check if enough budget
            return epsilon_remaining >= epsilon_needed, epsilon_remaining
    
    def deduct_budget(self, post_id: int, window_id: int, epsilon_used: float, conn=None) -> float:
        """
        Deduct epsilon from budget after a query.
        
        Args:
            post_id: The post ID
            window_id: The release window
            epsilon_used: Amount of epsilon consumed
            conn: Optional existing connection to reuse (avoids deadlock)
            
        Returns:
            Remaining epsilon budget
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
        
        # Deduct budget and check if should lock
        cursor.execute("""
            UPDATE epsilon_budget
            SET epsilon_remaining = epsilon_remaining - %s,
                is_locked = CASE 
                    WHEN (epsilon_remaining - %s) < %s THEN TRUE 
                    ELSE FALSE 
                END,
                locked_at = CASE 
                    WHEN (epsilon_remaining - %s) < %s THEN NOW() 
                    ELSE locked_at 
                END,
                last_updated = NOW()
            WHERE post_id = %s AND window_id = %s
            RETURNING epsilon_remaining, is_locked
        """, (epsilon_used, epsilon_used, EPSILON_PER_QUERY, 
            epsilon_used, EPSILON_PER_QUERY, post_id, window_id))
        
        result = cursor.fetchone()
        # Don't commit here - let caller handle commit
        
        if result:
            if result['is_locked']:
                print(f"⚠️ Post {post_id} budget exhausted! Locked.")
            return result['epsilon_remaining']
        else:
            raise Exception(f"Budget entry not found for post {post_id}, window {window_id}")
    
    def get_remaining_budget(self, post_id: int, window_id: int) -> Optional[float]:
        """
        Get remaining budget for a post in a window.
        
        Args:
            post_id: The post ID
            window_id: The release window
            
        Returns:
            Remaining epsilon, or None if no entry exists
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT epsilon_remaining
                FROM epsilon_budget
                WHERE post_id = %s AND window_id = %s
            """, (post_id, window_id))
            
            result = cursor.fetchone()
            return result['epsilon_remaining'] if result else None
    
    def is_locked(self, post_id: int) -> bool:
        """
        Quick check if post is currently locked (uses dp_items cache).
        
        Args:
            post_id: The post ID
            
        Returns:
            True if locked, False otherwise
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
    
    def _initialize_budget(self, post_id: int, window_id: int, conn):
        """
        Initialize budget for a new post/window combination.
        
        Args:
            post_id: The post ID
            window_id: The release window
            conn: Database connection
        """
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO epsilon_budget
            (post_id, window_id, epsilon_remaining, monthly_epsilon_cap)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (post_id, window_id) DO NOTHING
        """, (post_id, window_id, self.monthly_cap, self.monthly_cap))
        
        conn.commit()
    
    def reset_budget(self, post_id: int, window_id: int):
        """
        Reset budget for a post (useful for new windows).
        
        Args:
            post_id: The post ID
            window_id: The release window
        """
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE epsilon_budget
                SET epsilon_remaining = monthly_epsilon_cap,
                    is_locked = FALSE,
                    locked_at = NULL,
                    last_updated = NOW()
                WHERE post_id = %s AND window_id = %s
            """, (post_id, window_id))
            
            conn.commit()


def test_budget_tracker():
    """Test budget tracker functionality"""
    print("Testing Budget Tracker...")
    print("=" * 60)
    
    tracker = BudgetTracker(monthly_cap=5.0)  # Small cap for testing
    
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
    
    # ✅ CREATE THE WINDOW FIRST!
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
    print("  ✓ Passed: New post has full budget")
    
    # Test 2: Deduct budget
    print("\nTest 2: Deduct budget (0.5 epsilon)")
    remaining = tracker.deduct_budget(test_post_id, test_window_id, 0.5)
    print(f"  Remaining after deduction: {remaining}")
    assert remaining == 4.5
    print("  ✓ Passed: Budget deducted correctly")
    
    # Test 3: Check remaining
    print("\nTest 3: Check remaining budget")
    remaining = tracker.get_remaining_budget(test_post_id, test_window_id)
    print(f"  Remaining: {remaining}")
    assert remaining == 4.5
    print("  ✓ Passed: Remaining budget correct")
    
    # Test 4: Exhaust budget
    print("\nTest 4: Exhaust budget")
    for i in range(10):
        has_budget, remaining = tracker.check_budget(test_post_id, test_window_id, 0.5)
        print(f"  Iteration {i+1}: has_budget={has_budget}, remaining={remaining:.1f}")
        
        if has_budget:
            tracker.deduct_budget(test_post_id, test_window_id, 0.5)
        else:
            print(f"  Budget exhausted after {i+1} attempts!")
            break
    
    # Test 5: Check if locked
    print("\nTest 5: Check if post is locked")
    is_locked = tracker.is_locked(test_post_id)
    print(f"  Is locked: {is_locked}")
    assert is_locked is True
    print("  ✓ Passed: Post is locked when budget exhausted")
    
    # Clean up
    print("\nCleanup: Removing test data")
    with get_dp_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM epsilon_budget WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM dp_releases WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM dp_items WHERE post_id = %s", (test_post_id,))
        cursor.execute("DELETE FROM release_windows WHERE window_id = %s", (test_window_id,))
        conn.commit()
    print("  ✓ Cleanup complete")
    
    print("\n" + "=" * 60)
    print("✓ All budget tracker tests passed!")


if __name__ == "__main__":
    test_budget_tracker()