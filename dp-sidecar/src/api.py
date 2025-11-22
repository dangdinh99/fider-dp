"""
FastAPI service for the fider-dp sidecar.

Endpoints:
- POST /rate  → submit or update a rating
- GET /items/{item_id}/stats → return differentially private stats

This file depends on:
- dp_mechanism.py  (DP logic)
- database/__init__.py (SQLite functions)
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import dp_mechanism

from database import upsert_rating, get_item_stats


# -------------------------------------------------------------------
# DP configuration
# -------------------------------------------------------------------
EPS_MEAN = 0.5
EPS_COUNT = 0.5
RATING_THRESHOLD = 10


# -------------------------------------------------------------------
# Pydantic request/response models
# -------------------------------------------------------------------
class RatingIn(BaseModel):
    item_id: str = Field(..., description="ID of the item being rated")
    user_id: str = Field(..., description="Unique user ID (can be hashed)")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1 to 5")


class DPStatsOut(BaseModel):
    item_id: str
    dp_avg: float | None
    dp_count: int | None
    true_count: int
    threshold: int
    status: str


# -------------------------------------------------------------------
# FastAPI app
# -------------------------------------------------------------------
app = FastAPI(
    title="DP Sidecar",
    description="Differentially Private aggregator for Fider-like ratings.",
    version="0.1.0",
)


@app.get("/health")
def health_check():
    return {"status": "ok"}


# -------------------------------------------------------------------
# Submit rating
# -------------------------------------------------------------------
@app.post("/rate")
def submit_rating(payload: RatingIn):
    """
    Store or overwrite a user's rating for an item.
    """
    rating_value = max(1, min(5, payload.rating))

    try:
        upsert_rating(
            item_id=payload.item_id,
            user_id=payload.user_id,
            rating=rating_value,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    return {
        "status": "ok",
        "message": "Rating stored.",
        "item_id": payload.item_id,
        "user_id": payload.user_id,
        "rating": rating_value,
    }


# -------------------------------------------------------------------
# Get DP statistics
# -------------------------------------------------------------------
@app.get("/items/{item_id}/stats", response_model=DPStatsOut)
def fetch_item_stats(item_id: str):
    """
    Return DP average + DP count if enough ratings exist.
    Otherwise return a "not enough ratings" message.
    """
    try:
        true_count, true_sum = get_item_stats(item_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    
    if true_count == 0:
        return DPStatsOut(
            item_id=item_id,
            dp_avg=None,
            dp_count=None,
            true_count=0,
            threshold=RATING_THRESHOLD,
            status="no_ratings",
        )

    if true_count < RATING_THRESHOLD:
        return DPStatsOut(
            item_id=item_id,
            dp_avg=None,
            dp_count=None,
            true_count=true_count,
            threshold=RATING_THRESHOLD,
            status="not_enough_ratings",
        )
        
    dp_avg = dp_mechanism.dp_mean(
        true_sum=true_sum,
        true_count=true_count,
        epsilon_sum=EPS_MEAN,
    )

    dp_cnt = dp_mechanism.dp_count(
        true_count=true_count,
        epsilon_count=EPS_COUNT,
    )

    return DPStatsOut(
        item_id=item_id,
        dp_avg=dp_avg,
        dp_count=dp_cnt,
        true_count=true_count,
        threshold=RATING_THRESHOLD,
        status="ok",
    )


# -------------------------------------------------------------------
# Local dev runner
# -------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)