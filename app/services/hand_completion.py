"""Hand completion: finalize hand, process auto-leaves, trigger next hand."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hand import Hand, HandPlayer, HandResult, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.chip_service import apply_game_delta
from app.services.hand_service import _log_action
from app.services.leaderboard_service import invalidate_leaderboard_cache
from app.services.snapshot_service import bump_snapshot, fire_table_event

logger = logging.getLogger(__name__)

# Guard against multiple concurrent consolidation tasks
_consolidation_in_progress = False



async def complete_hand(
    session: AsyncSession,
    hand: Hand,
    showdown_result: dict[str, Any],
) -> None:
    """Finalise a hand that has just been resolved via showdown / fold-win.

    Steps:
    1. Mark hand FINISHED, record result JSON.
    2. Evict stack-0 players and LEAVING_AFTER_HAND players.
    3. Bump table snapshot version.
    4. Schedule next hand in background if conditions are met.
    """
    # --- 1. Finish the hand ---
    hand.status = HandStatus.FINISHED
    hand.finished_at = datetime.now(timezone.utc)
    invalidate_leaderboard_cache()

    await _log_action(session, hand.id, "HAND_FINISHED", hand.street)

    players_result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = list(players_result.scalars().all())

    # Build result JSON
    result_json: dict[str, Any] = {
        "board": json.loads(hand.board_json),
        "pot_view": showdown_result.get("pot_view", {}),
        "awards": showdown_result.get("awards", {}),
        "summaries": showdown_result.get("summaries", []),
        "players": [
            {
                "seat_no": p.seat_no,
                "account_id": p.account_id,
                "starting_stack": p.starting_stack,
                "ending_stack": p.ending_stack,
                "folded": p.folded,
                "all_in": p.all_in,
                "hole_cards": json.loads(p.hole_cards_json),
            }
            for p in players
        ],
    }
    session.add(HandResult(hand_id=hand.id, result_json=json.dumps(result_json)))

    await session.flush()

    # --- 2. Post-hand seat processing ---
    table_result = await session.execute(
        select(Table).where(Table.id == hand.table_id)
    )
    table = table_result.scalar_one()

    seats_result = await session.execute(
        select(TableSeat).where(TableSeat.table_id == hand.table_id)
    )
    seat_map = {s.seat_no: s for s in seats_result.scalars().all()}

    player_map = {p.seat_no: p for p in players}

    busted_players: list[dict] = []  # players eliminated this hand (stack → 0)

    for seat_no, seat in seat_map.items():
        if seat.account_id is None:
            continue
        hp = player_map.get(seat_no)
        if hp is None:
            continue  # spectator / joined mid-hand

        # Apply net chip change (win/loss) to the account wallet.
        # wallet_balance is the account's total chip count including chips in play.
        delta = hp.ending_stack - hp.starting_stack
        await apply_game_delta(session, seat.account_id, delta, hand.id)

        # Sync seat stack from ending_stack
        seat.stack = hp.ending_stack

        # Stack-0 auto-evict (no cashout needed; wallet already updated above)
        if seat.stack == 0 and seat.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND):
            busted_players.append({"account_id": seat.account_id, "seat_no": seat_no})
            seat.seat_status = SeatStatus.EMPTY
            seat.account_id = None
            continue

        # LEAVING_AFTER_HAND → evict (wallet already updated; just clear seat)
        if seat.seat_status == SeatStatus.LEAVING_AFTER_HAND:
            seat.stack = 0
            seat.seat_status = SeatStatus.EMPTY
            seat.account_id = None

    # --- 3. Bump snapshot (version only; full state will be rebuilt on next read) ---
    await bump_snapshot(session, hand.table_id)

    # --- 4. Check remaining players & auto-consolidation ---
    seats_after_q = await session.execute(
        select(TableSeat).where(TableSeat.table_id == hand.table_id)
    )
    eligible_after = [
        s for s in seats_after_q.scalars().all()
        if s.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND)
        and s.stack > 0
    ]

    # Check if tables can be consolidated (e.g. 2 tables → 1 when total ≤ 9)
    needs_consolidation = False
    all_active_tables: list[Table] = []

    all_tables_r = await session.execute(
        select(Table)
        .where(Table.status.in_([TableStatus.OPEN, TableStatus.PAUSED]))
        .options(selectinload(Table.seats))
    )
    all_active_tables = list(all_tables_r.scalars().all())

    if len(all_active_tables) >= 2:
        total_survivors = sum(
            1 for t in all_active_tables for s in t.seats
            if s.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND)
            and s.stack > 0
        )
        max_seats = table.max_seats  # 9
        tables_needed = max(1, -(-total_survivors // max_seats))  # ceil division

        if tables_needed < len(all_active_tables) and total_survivors > 1 and not _consolidation_in_progress:
            needs_consolidation = True
            # Pause all tables to prevent new hands while consolidating
            for t in all_active_tables:
                if t.status == TableStatus.OPEN:
                    t.status = TableStatus.PAUSED

    # Tournament winner: exactly 1 player remaining across ALL tables
    if not needs_consolidation and len(eligible_after) == 1 and len(all_active_tables) <= 1:
        # Runner-up: player(s) who busted in this final hand
        for bp in busted_players:
            await _log_action(
                session, hand.id, "TOURNAMENT_RUNNER_UP", None,
                actor_account_id=bp["account_id"],
                actor_seat_no=bp["seat_no"],
                is_system=True,
            )
            logger.info(
                "TOURNAMENT_RUNNER_UP: table=%d seat=%d account=%d",
                table.table_no, bp["seat_no"], bp["account_id"],
            )

        winner_seat = eligible_after[0]
        await _log_action(
            session, hand.id, "TOURNAMENT_WINNER", None,
            actor_account_id=winner_seat.account_id,
            actor_seat_no=winner_seat.seat_no,
            is_system=True,
        )
        table.status = TableStatus.PAUSED
        logger.info(
            "TOURNAMENT_WINNER: table=%d seat=%d account=%d",
            table.table_no, winner_seat.seat_no, winner_seat.account_id,
        )

    await session.commit()

    # Invalidate in-process state cache and notify SSE/long-poll waiters after commit.
    from app.api.public.game_state import invalidate_state_cache
    invalidate_state_cache(hand.table_id)
    fire_table_event(hand.table_id)

    if needs_consolidation:
        # Notify all table clients about the pause
        for t in all_active_tables:
            if t.id != hand.table_id:
                invalidate_state_cache(t.id)
                fire_table_event(t.id)
        logger.info(
            "Auto-consolidate triggered: %d survivors across %d tables (need %d table(s))",
            total_survivors, len(all_active_tables), tables_needed,
        )
        asyncio.ensure_future(_auto_consolidate())
        return

    # --- 5. Schedule next hand (only when 2+ players remain) ---
    if table.status == TableStatus.OPEN and len(eligible_after) >= 2:
        asyncio.ensure_future(_delayed_next_hand(hand.table_id))


async def _delayed_next_hand(table_id: int) -> None:
    """Wait 2 s then start the next hand if conditions still hold."""
    await asyncio.sleep(2)

    from app.database import async_session_factory
    from app.services.hand_service import get_active_hand, start_hand
    from app.core.table_lock import get_table_lock

    async with async_session_factory() as session:
        # Resolve table_no for lock
        t_result = await session.execute(select(Table).where(Table.id == table_id))
        table = t_result.scalar_one_or_none()
        if table is None or table.status != TableStatus.OPEN:
            return

        # Check no hand already running
        active = await get_active_hand(session, table_id)
        if active is not None:
            return

        # Need >= 2 seated players with stack > 0
        seats_result = await session.execute(
            select(TableSeat).where(TableSeat.table_id == table_id)
        )
        eligible = [
            s for s in seats_result.scalars().all()
            if s.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND)
            and s.stack > 0
        ]
        if len(eligible) < 2:
            return

        async with get_table_lock(table.table_no):
            await start_hand(session, table_id)


async def _auto_consolidate() -> None:
    """Background: wait for active hands to finish, then merge tables into fewer."""
    global _consolidation_in_progress
    _consolidation_in_progress = True
    try:
        await _run_consolidation()
    finally:
        _consolidation_in_progress = False


async def _run_consolidation() -> None:
    from app.database import async_session_factory
    from app.services.table_service import merge_tables

    # Wait for all in-progress hands to finish (max ~60s)
    for _ in range(60):
        await asyncio.sleep(1)
        async with async_session_factory() as session:
            active_r = await session.execute(
                select(Hand)
                .join(Table, Hand.table_id == Table.id)
                .where(
                    Hand.status == HandStatus.IN_PROGRESS,
                    Table.status.in_([TableStatus.OPEN, TableStatus.PAUSED]),
                )
            )
            if not active_r.scalars().first():
                break
    else:
        logger.error("Auto-consolidate: timed out waiting for active hands to finish")
        return

    dst_table_id: int | None = None

    async with async_session_factory() as session:
        # Re-query paused tables with seats
        tables_r = await session.execute(
            select(Table)
            .where(Table.status == TableStatus.PAUSED)
            .options(selectinload(Table.seats))
        )
        paused_tables = list(tables_r.scalars().all())

        if len(paused_tables) < 2:
            logger.info("Auto-consolidate: fewer than 2 paused tables, skipping")
            return

        # Pick destination = table with most seated players
        def _player_count(t: Table) -> int:
            return sum(
                1 for s in t.seats
                if s.seat_status == SeatStatus.SEATED and s.stack > 0
            )

        paused_tables.sort(key=_player_count, reverse=True)
        dst_table = paused_tables[0]
        dst_table_id = dst_table.id
        src_tables = [t for t in paused_tables[1:] if _player_count(t) > 0]

        if not src_tables:
            logger.info("Auto-consolidate: no source tables with players, skipping")
            return

        # Merge each source into destination
        for src in src_tables:
            try:
                result = await merge_tables(session, src.table_no, dst_table.table_no)
                logger.info(
                    "Auto-consolidate: merged table %d → %d (%s)",
                    src.table_no, dst_table.table_no, result,
                )
            except Exception:
                logger.exception("Auto-consolidate: merge table %d → %d failed", src.table_no, dst_table.table_no)
                return

        # Close empty source tables, open destination
        for src in src_tables:
            src_r = await session.execute(select(Table).where(Table.id == src.id))
            s = src_r.scalar_one()
            s.status = TableStatus.CLOSED

        dst_r = await session.execute(select(Table).where(Table.id == dst_table.id))
        dst = dst_r.scalar_one()
        dst.status = TableStatus.OPEN
        await session.commit()

        # Bump snapshot & notify clients
        await bump_snapshot(session, dst.id)
        await session.commit()

        from app.api.public.game_state import invalidate_state_cache
        invalidate_state_cache(dst.id)
        fire_table_event(dst.id)
        for src in src_tables:
            invalidate_state_cache(src.id)
            fire_table_event(src.id)

        logger.info("Auto-consolidate: table %d now OPEN with all players", dst.table_no)

    # Schedule next hand on consolidated table
    if dst_table_id:
        asyncio.ensure_future(_delayed_next_hand(dst_table_id))
