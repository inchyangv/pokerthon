"""Periodic nonce cleanup background task.

Deletes api_nonces records older than 10 minutes (timestamp + 600s) every 5 minutes.
"""
from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import delete

from app.database import async_session_factory
from app.models.credential import ApiNonce

logger = logging.getLogger(__name__)

_CLEANUP_INTERVAL = 300  # seconds (5 minutes)
_NONCE_TTL = 600          # seconds (10 minutes)


async def _cleanup_once() -> int:
    """Delete expired nonces. Returns the number of deleted records."""
    cutoff = int(time.time()) - _NONCE_TTL
    async with async_session_factory() as session:
        result = await session.execute(
            delete(ApiNonce).where(ApiNonce.timestamp <= cutoff)
        )
        await session.commit()
        deleted = result.rowcount
    if deleted:
        logger.info("Nonce cleanup: deleted %d expired records", deleted)
    return deleted


async def nonce_cleanup_loop() -> None:
    """Infinite loop: clean up expired nonces every CLEANUP_INTERVAL seconds."""
    logger.info("Nonce cleanup task started (interval=%ds, ttl=%ds)", _CLEANUP_INTERVAL, _NONCE_TTL)
    while True:
        try:
            await _cleanup_once()
        except Exception:
            logger.exception("Unexpected error in nonce_cleanup_loop")
        await asyncio.sleep(_CLEANUP_INTERVAL)
