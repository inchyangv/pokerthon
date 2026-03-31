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
from app.models.table import SeatStatus, Table, TableSeat

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

    # Load table for big_blind (needed for legal action computation)
    table_result_early = await session.execute(select(Table).where(Table.id == seat.table_id))
    table_early = table_result_early.scalar_one()

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
    raw_legal = get_legal_actions(hand, player, table_early.big_blind)
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
    table = table_early

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


async def _auto_start_hands() -> None:
    """Start hands on tables with >= 2 seated players but no active hand."""
    from app.models.table import Table, TableStatus
    from app.services.hand_service import get_active_hand, start_hand
    from app.core.table_lock import get_table_lock

    async with async_session_factory() as session:
        tables_result = await session.execute(
            select(Table).where(Table.status == TableStatus.OPEN)
        )
        tables = list(tables_result.scalars().all())

    for table in tables:
        try:
            async with async_session_factory() as session:
                active = await get_active_hand(session, table.id)
                if active is not None:
                    continue

                seats_result = await session.execute(
                    select(TableSeat).where(TableSeat.table_id == table.id)
                )
                eligible = [
                    s for s in seats_result.scalars().all()
                    if s.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND)
                    and s.stack > 0
                ]
                if len(eligible) < 2:
                    continue

                async with get_table_lock(table.table_no):
                    # Re-check inside lock to prevent duplicates
                    active_recheck = await get_active_hand(session, table.id)
                    if active_recheck is not None:
                        continue
                    hand = await start_hand(session, table.id)
                    if hand:
                        logger.info("Auto-started hand at table %d", table.table_no)
        except Exception:
            logger.exception("Error auto-starting hand at table %d", table.table_no)


async def _refill_and_reseat_bots() -> None:
    """Refill chips and reseat any active bot that is no longer seated."""
    if not settings.BOT_AUTO_RESEAT:
        return

    from app.models.account import Account
    from app.models.table import Table, TableStatus
    from app.services.chip_service import grant as chip_grant
    from app.services.bot_service import seat_bot

    async with async_session_factory() as session:
        # All active bots
        bots_r = await session.execute(
            select(BotProfile).where(BotProfile.is_active == True)  # noqa: E712
        )
        bots = list(bots_r.scalars().all())

        for bot in bots:
            # Skip if already seated
            seat_r = await session.execute(
                select(TableSeat).where(
                    TableSeat.account_id == bot.account_id,
                    TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
                )
            )
            if seat_r.scalar_one_or_none():
                continue

            # Refill chips if wallet is below buy-in
            acc_r = await session.execute(select(Account).where(Account.id == bot.account_id))
            account = acc_r.scalar_one_or_none()
            if not account:
                continue

            if account.wallet_balance < settings.TABLE_BUYIN:
                await chip_grant(session, bot.account_id, settings.BOT_RESEAT_CHIPS, reason_text="bot_reseat")
                await session.refresh(account)

            # Reseat at home table if set; fall back to any open table
            target_table_no = bot.home_table_no
            if target_table_no:
                table_r = await session.execute(
                    select(Table).where(Table.table_no == target_table_no, Table.status == TableStatus.OPEN)
                )
                table = table_r.scalar_one_or_none()
                if table:
                    seats_r = await session.execute(
                        select(TableSeat).where(TableSeat.table_id == table.id)
                    )
                    has_empty = any(s.seat_status == SeatStatus.EMPTY for s in seats_r.scalars().all())
                    if has_empty:
                        try:
                            async with get_table_lock(table.table_no):
                                await seat_bot(session, bot.id, table.table_no)
                            logger.info("Bot %s reseated at home table %d", bot.display_name, table.table_no)
                            continue
                        except Exception:
                            pass  # Fall through to any-table search

            # Fallback: find any open table with an empty seat
            tables_r = await session.execute(
                select(Table).where(Table.status == TableStatus.OPEN).order_by(Table.table_no)
            )
            for table in tables_r.scalars().all():
                seats_r = await session.execute(
                    select(TableSeat).where(TableSeat.table_id == table.id)
                )
                if any(s.seat_status == SeatStatus.EMPTY for s in seats_r.scalars().all()):
                    try:
                        async with get_table_lock(table.table_no):
                            await seat_bot(session, bot.id, table.table_no)
                        logger.info("Bot %s reseated at table %d (fallback)", bot.display_name, table.table_no)
                        break
                    except Exception:
                        continue


async def bot_runner_loop() -> None:
    """Main bot runner loop. Polls all active bots and processes their turns."""
    if not settings.BOT_ENABLED:
        logger.info("Bot runner disabled (BOT_ENABLED=False)")
        return

    logger.info("Bot runner started (poll_interval=%.1fs)", settings.BOT_POLL_INTERVAL)

    while True:
        try:
            # Refill and reseat evicted bots
            await _refill_and_reseat_bots()

            # Auto-start hands on tables with enough players
            await _auto_start_hands()

            async with async_session_factory() as session:
                # Load all active bot profiles
                result = await session.execute(
                    select(BotProfile).where(BotProfile.is_active == True)  # noqa: E712
                )
                bots = list(result.scalars().all())

            # Process each bot independently (parallel to avoid serial delay stacking)
            async def _safe_process(bp: BotProfile) -> None:
                try:
                    async with async_session_factory() as session:
                        await _process_bot_turn(session, bp)
                except Exception:
                    logger.exception("Error processing bot %s", bp.display_name)

            await asyncio.gather(*[_safe_process(bp) for bp in bots])

        except Exception:
            logger.exception("Error in bot runner loop")

        await asyncio.sleep(settings.BOT_POLL_INTERVAL)
