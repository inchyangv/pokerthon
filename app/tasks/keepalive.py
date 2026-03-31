"""Background keepalive: pre-warm leaderboard cache and keep DB connections alive."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)
_INTERVAL = 55  # seconds — just under Railway's 60-second idle timeout


async def keepalive_loop() -> None:
    """Refresh leaderboard cache every ~55 s to prevent cold-query latency on first visitor."""
    await asyncio.sleep(30)  # let startup complete first
    while True:
        try:
            from app.database import async_session_factory
            from app.services.leaderboard_service import get_leaderboard

            async with async_session_factory() as session:
                await get_leaderboard(session, sort_by="chips", limit=5)
            logger.debug("keepalive: leaderboard cache refreshed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("keepalive: refresh failed (non-fatal)", exc_info=True)
        await asyncio.sleep(_INTERVAL)
