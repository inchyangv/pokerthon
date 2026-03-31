"""Automatic blind escalation background task.

Reads TOURNAMENT_START_AT and BLIND_LEVEL_HOURS from config and
escalates all table blinds on schedule:
  Level 0 (start):  SB=1  BB=2
  Level 1 (+48h):   SB=2  BB=4
  Level 2 (+96h):   SB=3  BB=6
  Level 3 (+144h):  SB=4  BB=8
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

BLIND_SCHEDULE: list[tuple[int, int]] = [
    (1, 2),
    (2, 4),
    (3, 6),
    (4, 8),
]

_POLL_INTERVAL = 60  # seconds


def get_current_level(now: datetime | None = None) -> int:
    """Return 0-based blind level index for the given moment."""
    if settings.TOURNAMENT_START_AT is None:
        return 0
    if now is None:
        now = datetime.now(timezone.utc)
    start = settings.TOURNAMENT_START_AT
    # Ensure both are timezone-aware for comparison
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if now < start:
        return 0
    elapsed_hours = (now - start).total_seconds() / 3600
    level = int(elapsed_hours // settings.BLIND_LEVEL_HOURS)
    return min(level, len(BLIND_SCHEDULE) - 1)


def get_blind_level_info(now: datetime | None = None) -> dict[str, Any]:
    """Return current blind level info for display in the viewer."""
    if now is None:
        now = datetime.now(timezone.utc)
    enabled = settings.TOURNAMENT_START_AT is not None
    level = get_current_level(now)
    sb, bb = BLIND_SCHEDULE[level]

    next_level = level + 1
    next_level_at: datetime | None = None
    next_sb: int | None = None
    next_bb: int | None = None

    if enabled and next_level < len(BLIND_SCHEDULE):
        start = settings.TOURNAMENT_START_AT
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        next_level_at = start + timedelta(hours=next_level * settings.BLIND_LEVEL_HOURS)
        next_sb, next_bb = BLIND_SCHEDULE[next_level]

    return {
        "enabled": enabled,
        "level": level + 1,           # 1-indexed for display
        "small_blind": sb,
        "big_blind": bb,
        "next_level_at": next_level_at.isoformat() if next_level_at else None,
        "next_small_blind": next_sb,
        "next_big_blind": next_bb,
    }


async def _apply_blinds_if_needed() -> None:
    now = datetime.now(timezone.utc)
    level = get_current_level(now)
    sb, bb = BLIND_SCHEDULE[level]

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.table import Table, TableStatus

    async with async_session_factory() as session:
        result = await session.execute(
            select(Table).where(Table.status != TableStatus.CLOSED)
        )
        tables = list(result.scalars().all())

        updated = []
        for table in tables:
            if table.small_blind != sb or table.big_blind != bb:
                table.small_blind = sb
                table.big_blind = bb
                updated.append(table.table_no)

        if updated:
            await session.commit()
            logger.info(
                "Blind escalation: level=%d blinds=%d/%d applied to tables %s",
                level, sb, bb, updated,
            )


async def blind_escalation_loop() -> None:
    if settings.TOURNAMENT_START_AT is None:
        logger.info("Blind escalation disabled (TOURNAMENT_START_AT not set)")
        return

    logger.info(
        "Blind escalation started: start=%s schedule=%s interval=%dh",
        settings.TOURNAMENT_START_AT.isoformat(),
        BLIND_SCHEDULE,
        settings.BLIND_LEVEL_HOURS,
    )
    while True:
        try:
            await _apply_blinds_if_needed()
        except Exception:
            logger.exception("Error in blind_escalation_loop")
        await asyncio.sleep(_POLL_INTERVAL)
