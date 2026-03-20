"""Auto-fold timeout background task.

Polls all IN_PROGRESS hands every ~5 seconds and auto-folds any player
whose action_deadline_at has passed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.action_validator import ActionError
from app.core.table_lock import get_table_lock
from app.database import async_session_factory
from app.models.hand import Hand, HandStatus
from app.models.table import Table
from app.services.action_service import process_action

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5  # seconds


async def _check_once() -> None:
    """Single pass: find overdue actions and auto-fold them."""
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        result = await session.execute(
            select(Hand).where(
                Hand.status == HandStatus.IN_PROGRESS,
                Hand.action_deadline_at.isnot(None),
                Hand.action_deadline_at <= now,
                Hand.action_seat_no.isnot(None),
            )
        )
        overdue_hands = list(result.scalars().all())

    for hand in overdue_hands:
        async with async_session_factory() as session:
            # Re-fetch inside its own session
            fresh = await session.get(Hand, hand.id)
            if fresh is None or fresh.status != HandStatus.IN_PROGRESS:
                continue
            if fresh.action_seat_no is None or fresh.action_deadline_at is None:
                continue
            if fresh.action_deadline_at > now:
                continue

            # Identify the acting account
            from app.models.hand import HandPlayer
            hp_result = await session.execute(
                select(HandPlayer).where(
                    HandPlayer.hand_id == fresh.id,
                    HandPlayer.seat_no == fresh.action_seat_no,
                )
            )
            hp = hp_result.scalar_one_or_none()
            if hp is None:
                continue

            # Get table_no for lock
            table_result = await session.execute(select(Table).where(Table.id == fresh.table_id))
            table = table_result.scalar_one_or_none()
            if table is None:
                continue

            lock = get_table_lock(table.table_no)
            async with lock:
                # Re-check still overdue
                await session.refresh(fresh)
                if fresh.status != HandStatus.IN_PROGRESS:
                    continue
                if fresh.action_deadline_at is None or fresh.action_deadline_at > datetime.now(timezone.utc):
                    continue

                logger.info(
                    "AUTO_FOLD_TIMEOUT: hand=%d seat=%d account=%d",
                    fresh.id, fresh.action_seat_no, hp.account_id,
                )
                try:
                    # Override the action type to auto-fold
                    # We need to log AUTO_FOLD_TIMEOUT, not FOLD, so we handle it specially
                    await _auto_fold(session, fresh, hp.account_id)
                except Exception:
                    logger.exception("Error processing auto-fold for hand=%d", fresh.id)


async def _auto_fold(session, hand: Hand, account_id: int) -> None:
    """Process an auto-fold due to timeout, logging as AUTO_FOLD_TIMEOUT."""
    from app.models.hand import HandAction, HandPlayer
    from app.services.hand_service import _log_action, _next_seq
    from app.services.round_service import advance_street

    # Mark player as folded directly (bypassing process_action to use custom action type)
    hp_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.account_id == account_id)
    )
    player = hp_result.scalar_one_or_none()
    if player is None:
        return

    player.folded = True

    # Log AUTO_FOLD_TIMEOUT
    await _log_action(
        session, hand.id, "AUTO_FOLD_TIMEOUT", hand.street,
        actor_account_id=account_id,
        actor_seat_no=player.seat_no,
        is_system=True,
    )

    await session.flush()

    # Check if round / game advances
    advanced = await advance_street(session, hand)
    if not advanced:
        from app.services.action_service import _advance_action
        await _advance_action(session, hand)
    else:
        await session.refresh(hand)
        if hand.street == "showdown":
            from app.services.showdown_service import resolve_showdown
            from app.services.hand_completion import complete_hand
            result = await resolve_showdown(session, hand)
            await complete_hand(session, hand, result)
            return

    await session.commit()


async def timeout_checker_loop() -> None:
    """Infinite loop: check every POLL_INTERVAL seconds."""
    logger.info("Timeout checker started (poll interval=%ds)", _POLL_INTERVAL)
    while True:
        try:
            await _check_once()
        except Exception:
            logger.exception("Unexpected error in timeout_checker_loop")
        await asyncio.sleep(_POLL_INTERVAL)
