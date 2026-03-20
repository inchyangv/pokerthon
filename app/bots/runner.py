"""Bot runner background task — polls for bot turns and submits actions."""
from __future__ import annotations

import asyncio
import json
import logging
import random

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bots import BotType
from app.bots.strategy import decide
from app.config import settings
from app.core.legal_actions import get_legal_actions
from app.core.table_lock import get_table_lock
from app.database import async_session_factory
from app.models.bot import BotProfile
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, TableSeat

logger = logging.getLogger(__name__)


def _normalize_legal_actions(raw: list[dict]) -> list[dict]:
    """Convert internal legal action format to strategy engine format."""
    normalized = []
    for a in raw:
        atype = a.get("type") or a.get("action_type")
        entry: dict = {"action_type": atype}
        if "min" in a:
            entry["min_amount"] = a["min"]
        if "max" in a:
            entry["max_amount"] = a["max"]
        if "amount" in a and atype in ("CALL", "ALL_IN"):
            entry["amount"] = a["amount"]
        normalized.append(entry)
    return normalized


async def _process_bot_turn(session: AsyncSession, bot_profile: BotProfile) -> None:
    """Check if it's this bot's turn and submit an action if so."""
    # Find bot's current seat
    seat_result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == bot_profile.account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat = seat_result.scalar_one_or_none()
    if seat is None:
        return  # Not seated anywhere

    # Find active hand at this table
    hand_result = await session.execute(
        select(Hand).where(
            Hand.table_id == seat.table_id,
            Hand.status == HandStatus.IN_PROGRESS,
        )
    )
    hand = hand_result.scalar_one_or_none()
    if hand is None:
        return  # No active hand

    # Check it's the bot's turn
    if hand.action_seat_no != seat.seat_no:
        return

    # Load player record
    player_result = await session.execute(
        select(HandPlayer).where(
            HandPlayer.hand_id == hand.id,
            HandPlayer.account_id == bot_profile.account_id,
        )
    )
    player = player_result.scalar_one_or_none()
    if player is None or player.folded or player.all_in:
        return

    # Compute legal actions
    raw_legal = get_legal_actions(hand, player)
    if not raw_legal:
        return

    legal_actions = _normalize_legal_actions(raw_legal)

    # Extract hole cards
    hole_cards: list[str] = json.loads(player.hole_cards_json) if player.hole_cards_json else []
    if not hole_cards:
        return

    # Extract board
    board: list[str] = json.loads(hand.board_json) if hand.board_json else []

    # Compute pot size
    pot_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    all_players = list(pot_result.scalars().all())
    pot_size = sum(p.hand_contribution for p in all_players)
    to_call = max(0, hand.current_bet - player.round_contribution)

    # Artificial delay
    delay = random.uniform(settings.BOT_ACTION_DELAY_MIN, settings.BOT_ACTION_DELAY_MAX)
    await asyncio.sleep(delay)

    # Get bot decision
    bot_type = BotType(bot_profile.bot_type)
    decision = decide(
        bot_type=bot_type,
        street=hand.street,
        hole_cards=hole_cards,
        board=board,
        legal_actions=legal_actions,
        current_bet=hand.current_bet,
        to_call=to_call,
        stack=player.ending_stack,
        pot_size=pot_size,
    )

    # Map strategy action_type to action_service types
    # Strategy uses RAISE_TO/BET; action_service uses RAISE_TO/BET_TO
    action_type = decision.action_type
    if action_type == "BET":
        action_type = "BET_TO"

    amount = decision.amount

    # Acquire per-table lock and submit action
    # Load table_no for lock key
    from app.models.table import Table
    table_result = await session.execute(select(Table).where(Table.id == seat.table_id))
    table = table_result.scalar_one()

    lock = get_table_lock(table.table_no)
    async with lock:
        # Re-fetch hand inside lock (may have changed)
        await session.refresh(hand)
        if hand.status != HandStatus.IN_PROGRESS or hand.action_seat_no != seat.seat_no:
            return  # Already processed

        from app.services.action_service import process_action
        action = await process_action(session, hand, bot_profile.account_id, action_type, amount)
        logger.info(
            "Bot %s (seat %d) submitted %s amount=%s",
            bot_profile.display_name,
            seat.seat_no,
            action_type,
            amount,
        )

        # Update snapshot version
        from app.models.hand import TableSnapshot
        snap_result = await session.execute(
            select(TableSnapshot).where(TableSnapshot.table_id == table.id)
        )
        snap = snap_result.scalar_one_or_none()
        snapshot_data = {
            "hand_id": hand.id,
            "street": hand.street,
            "action_seat_no": hand.action_seat_no,
        }
        if snap:
            snap.version += 1
            snap.snapshot_json = json.dumps(snapshot_data)
        else:
            snap = TableSnapshot(
                table_id=table.id,
                version=1,
                snapshot_json=json.dumps(snapshot_data),
            )
            session.add(snap)

        await session.commit()


async def bot_runner_loop() -> None:
    """Main bot runner loop. Polls all active bots and processes their turns."""
    if not settings.BOT_ENABLED:
        logger.info("Bot runner disabled (BOT_ENABLED=False)")
        return

    logger.info("Bot runner started (poll_interval=%.1fs)", settings.BOT_POLL_INTERVAL)

    while True:
        try:
            async with async_session_factory() as session:
                # Load all active bot profiles
                result = await session.execute(
                    select(BotProfile).where(BotProfile.is_active == True)  # noqa: E712
                )
                bots = list(result.scalars().all())

            # Process each bot independently
            for bot_profile in bots:
                try:
                    async with async_session_factory() as session:
                        await _process_bot_turn(session, bot_profile)
                except Exception:
                    logger.exception("Error processing bot %s", bot_profile.display_name)

        except Exception:
            logger.exception("Error in bot runner loop")

        await asyncio.sleep(settings.BOT_POLL_INTERVAL)
