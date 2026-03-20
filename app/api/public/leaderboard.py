"""Public leaderboard API."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.leaderboard_service import get_leaderboard

router = APIRouter(prefix="/v1/public", tags=["leaderboard"])


@router.get("/leaderboard")
async def leaderboard(
    sort_by: str = Query(default="chips", pattern="^(chips|profit|win_rate|hands_played)$"),
    limit: int = Query(default=50, ge=1, le=200),
    include_bots: bool = Query(default=True),
    session: AsyncSession = Depends(get_session),
):
    items = await get_leaderboard(
        session, sort_by=sort_by, limit=limit, include_bots=include_bots
    )
    return {
        "items": items,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
