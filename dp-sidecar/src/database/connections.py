"""
Database connection helpers.
Provides functions to connect to both Fider's DB and our DP DB.
"""
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
import sys
import os

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import FIDER_DB_CONFIG, DP_DB_CONFIG


@contextmanager
def get_fider_connection():
    """
    Get a connection to Fider's database (read-only).
    Use this to read votes and posts.
    
    Usage:
        with get_fider_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM votes WHERE post_id = %s", (post_id,))
            count = cursor.fetchone()[0]
    """
    conn = psycopg2.connect(**FIDER_DB_CONFIG, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_dp_connection():
    """
    Get a connection to our DP sidecar database (read-write).
    Use this to store DP releases and track budgets.
    
    Usage:
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO dp_releases ...")
            conn.commit()
    """
    conn = psycopg2.connect(**DP_DB_CONFIG, cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def get_true_count_from_fider(post_id: int) -> int:
    """
    Get the true vote count for a post from Fider's database.
    
    Args:
        post_id: The Fider post ID
        
    Returns:
        Number of votes for this post
    """
    with get_fider_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) AS count
            FROM post_votes
            WHERE post_id = %s
        """, (post_id,))
        result = cursor.fetchone()
        count = result['count'] if result else 0
    return count


def test_connections():
    """
    Test function to verify both database connections work.
    Run this to make sure everything is set up correctly.
    """
    print("Testing database connections...")
    print("=" * 60)
    
    # Test Fider connection
    try:
        with get_fider_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM posts")
            result = cursor.fetchone()
            post_count = result['count']
            print(f"✓ Fider DB connected: {post_count} posts found")
            
            cursor.execute("SELECT COUNT(*) as count FROM post_votes")
            result = cursor.fetchone()
            vote_count = result['count']
            print(f"✓ Fider DB: {vote_count} total votes")
    except Exception as e:
        print(f"✗ Fider DB connection failed: {e}")
        return False
    
    # Test DP sidecar connection
    try:
        with get_dp_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM dp_items")
            result = cursor.fetchone()
            item_count = result['count']
            print(f"✓ DP DB connected: {item_count} items tracked")
            
            cursor.execute("SELECT COUNT(*) as count FROM release_windows")
            result = cursor.fetchone()
            window_count = result['count']
            print(f"✓ DP DB: {window_count} release windows")
    except Exception as e:
        print(f"✗ DP DB connection failed: {e}")
        return False
    
    print("=" * 60)
    print("✓ All database connections working!")
    return True


if __name__ == "__main__":
    # Test connections when running this file directly
    test_connections()