"""Leaderboard statistics aggregation."""
from __future__ import annotations

import time

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.chip import ChipLedger, LedgerReasonType
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat

# In-memory cache: key → (timestamp, data)
_cache: dict[tuple, tuple[float, list[dict]]] = {}
_CACHE_TTL = 20.0  # seconds


def invalidate_leaderboard_cache() -> None:
    """Call this after a hand completes to clear stale data."""
    _cache.clear()


async def get_leaderboard(
    session: AsyncSession,
    sort_by: str = "chips",
    limit: int = 50,
    include_bots: bool = True,
) -> list[dict]:
    # ── 0. Cache check ───────────────────────────────────────────────────────
    cache_key = (sort_by, include_bots, limit)
    entry = _cache.get(cache_key)
    if entry is not None:
        ts, data = entry
        if time.monotonic() - ts < _CACHE_TTL:
            return data

    # ── 1. Load all accounts (1 query) ───────────────────────────────────────
    query = select(Account)
    if not include_bots:
        query = query.where(Account.is_bot == False)  # noqa: E712
    result = await session.execute(query)
    accounts = list(result.scalars().all())
    if not accounts:
        return []
    account_ids = [a.id for a in accounts]

    # ── 2. Load all active seats for these accounts (1 query) ────────────────
    seats_result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id.in_(account_ids),
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat_map: dict[int, TableSeat] = {s.account_id: s for s in seats_result.scalars().all()}

    # ── 3. Load tables for seated accounts (1 query) ─────────────────────────
    table_ids = list({s.table_id for s in seat_map.values()})
    table_no_map: dict[int, int] = {}  # table_id → table_no
    if table_ids:
        tables_result = await session.execute(
            select(Table).where(Table.id.in_(table_ids))
        )
        table_no_map = {t.id: t.table_no for t in tables_result.scalars().all()}

    # ── 4. Aggregate hand stats per account in SQL (1 query) ─────────────────
    # A player "won" a hand when ending_stack > starting_stack (net positive).
    profit_expr = HandPlayer.ending_stack - HandPlayer.starting_stack
    agg_result = await session.execute(
        select(
            HandPlayer.account_id,
            func.count().label("hands_played"),
            func.sum(
                case((HandPlayer.ending_stack > HandPlayer.starting_stack, 1), else_=0)
            ).label("hands_won"),
            func.max(
                case((HandPlayer.ending_stack > HandPlayer.starting_stack, profit_expr), else_=0)
            ).label("biggest_pot_won"),
        )
        .join(Hand, Hand.id == HandPlayer.hand_id)
        .where(
            HandPlayer.account_id.in_(account_ids),
            Hand.status == HandStatus.FINISHED,
        )
        .group_by(HandPlayer.account_id)
    )
    agg_by_account = {row.account_id: row for row in agg_result}

    # ── 5. Aggregate ADMIN_GRANT chips per account in SQL (1 query) ──────────
    grant_result = await session.execute(
        select(
            ChipLedger.account_id,
            func.sum(ChipLedger.delta).label("total_granted"),
        )
        .where(
            ChipLedger.account_id.in_(account_ids),
            ChipLedger.reason_type == LedgerReasonType.ADMIN_GRANT,
        )
        .group_by(ChipLedger.account_id)
    )
    granted_by_account: dict[int, int] = {row.account_id: int(row.total_granted) for row in grant_result}

    # ── 6. Assemble results in memory ────────────────────────────────────────
    items = []
    for account in accounts:
        seat = seat_map.get(account.id)
        table_stack = seat.stack if seat else 0
        current_table = table_no_map.get(seat.table_id) if seat else None

        total_chips = account.wallet_balance

        agg = agg_by_account.get(account.id)
        hands_played = int(agg.hands_played) if agg else 0
        hands_won = int(agg.hands_won) if agg else 0
        biggest_pot_won = int(agg.biggest_pot_won) if agg else 0

        win_rate = (hands_won / hands_played) if hands_played > 0 else 0.0
        total_granted = granted_by_account.get(account.id, 0)
        total_profit = total_chips - total_granted

        items.append({
            "nickname": account.nickname,
            "is_bot": account.is_bot,
            "total_chips": total_chips,
            "wallet_balance": account.wallet_balance,
            "table_stack": table_stack,
            "hands_played": hands_played,
            "hands_won": hands_won,
            "win_rate": round(win_rate, 4),
            "total_profit": total_profit,
            "biggest_pot_won": biggest_pot_won,
            "current_table": current_table,
        })

    # ── 7. Sort + slice ──────────────────────────────────────────────────────
    sort_key_map = {
        "chips": lambda x: -x["total_chips"],
        "profit": lambda x: -x["total_profit"],
        "win_rate": lambda x: (-x["win_rate"], -x["hands_played"]),
        "hands_played": lambda x: -x["hands_played"],
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["chips"])
    items.sort(key=key_fn)
    items = items[:limit]

    for i, item in enumerate(items, 1):
        item["rank"] = i

    _cache[cache_key] = (time.monotonic(), items)
    return items
