"""Server restart recovery: restore in-memory state for in-progress hands."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.table_lock import get_table_lock
from app.models.hand import Hand, HandStatus
from app.models.table import Table

logger = logging.getLogger(__name__)


async def recover_in_progress_hands(session: AsyncSession) -> int:
    """Re-initialise per-table asyncio.Locks for all hands still IN_PROGRESS.

    This ensures the timeout checker and new action requests work correctly
    after a server restart.  The actual hand data lives in the DB; we only
    need to make sure the in-memory lock exists for each table.

    Returns the number of hands recovered.
    """
    result = await session.execute(
        select(Hand).where(Hand.status == HandStatus.IN_PROGRESS)
    )
    in_progress = list(result.scalars().all())

    if not in_progress:
        logger.info("Recovery: no in-progress hands found")
        return 0

    table_ids = {h.table_id for h in in_progress}
    tables_result = await session.execute(select(Table).where(Table.id.in_(list(table_ids))))
    table_map = {t.id: t for t in tables_result.scalars().all()}

    for hand in in_progress:
        table = table_map.get(hand.table_id)
        if table is None:
            continue
        # Ensure the lock exists in memory
        get_table_lock(table.table_no)
        logger.info(
            "Recovery: restored lock for table_no=%d hand_id=%d",
            table.table_no, hand.id,
        )

    logger.info("Recovery: %d in-progress hand(s) recovered", len(in_progress))
    return len(in_progress)
