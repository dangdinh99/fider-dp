"""
SQLite-based storage layer for the fider-dp sidecar.

Responsibilities:
- Store ratings in a table (item_id, user_id, rating)
- Ensure one rating per user per item (UPSERT)
- Fetch true_count and true_sum of ratings
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "ratings.db"


# -------------------------------------------------------------------
# Internal connection helper
# -------------------------------------------------------------------
def _get_conn():
    """
    Returns a SQLite connection and ensures the ratings table exists.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            item_id TEXT,
            user_id TEXT,
            rating INTEGER,
            PRIMARY KEY (item_id, user_id)
        )
        """
    )
    return conn


# -------------------------------------------------------------------
# Insert or update a rating
# -------------------------------------------------------------------
def upsert_rating(item_id: str, user_id: str, rating: int) -> None:
    """
    Insert a new rating or update the existing one.

    (item_id, user_id) is unique → overwriting previous ratings is allowed.
    """
    conn = _get_conn()
    with conn:
        conn.execute(
            """
            INSERT INTO ratings (item_id, user_id, rating)
            VALUES (?, ?, ?)
            ON CONFLICT(item_id, user_id)
            DO UPDATE SET rating = excluded.rating;
            """,
            (item_id, user_id, rating),
        )
    conn.close()


# -------------------------------------------------------------------
# Return (true_count, true_sum)
# -------------------------------------------------------------------
def get_item_stats(item_id: str) -> tuple[int, float]:
    """
    Return how many ratings exist for this item,
    and the sum of all ratings.
    """
    conn = _get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(rating), 0)
        FROM ratings
        WHERE item_id = ?;
        """,
        (item_id,),
    )

    count, total = cur.fetchone()
    conn.close()

    return int(count), float(total or 0.0)