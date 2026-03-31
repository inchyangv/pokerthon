"""Leaderboard statistics aggregation."""
from __future__ import annotations

import json
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.chip import ChipLedger, LedgerReasonType
from app.models.hand import Hand, HandPlayer, HandResult, HandStatus
from app.models.table import SeatStatus, Table, TableSeat


async def get_leaderboard(
    session: AsyncSession,
    sort_by: str = "chips",
    limit: int = 50,
    include_bots: bool = True,
) -> list[dict]:
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

    # ── 4. Load all HandPlayers for finished hands (1 query) ─────────────────
    hp_result = await session.execute(
        select(HandPlayer)
        .join(Hand, Hand.id == HandPlayer.hand_id)
        .where(
            HandPlayer.account_id.in_(account_ids),
            Hand.status == HandStatus.FINISHED,
        )
    )
    hp_by_account: dict[int, list[HandPlayer]] = defaultdict(list)
    all_hand_ids: set[int] = set()
    for hp in hp_result.scalars().all():
        hp_by_account[hp.account_id].append(hp)
        all_hand_ids.add(hp.hand_id)

    # ── 5. Load all HandResults for those hands (1 query) ────────────────────
    hr_map: dict[int, HandResult] = {}
    if all_hand_ids:
        hr_result = await session.execute(
            select(HandResult).where(HandResult.hand_id.in_(all_hand_ids))
        )
        hr_map = {hr.hand_id: hr for hr in hr_result.scalars().all()}

    # ── 6. Load all ADMIN_GRANT ledger entries (1 query) ─────────────────────
    grant_result = await session.execute(
        select(ChipLedger).where(
            ChipLedger.account_id.in_(account_ids),
            ChipLedger.reason_type == LedgerReasonType.ADMIN_GRANT,
        )
    )
    granted_by_account: dict[int, int] = defaultdict(int)
    for g in grant_result.scalars().all():
        granted_by_account[g.account_id] += g.delta

    # ── 7. Assemble results in memory ────────────────────────────────────────
    items = []
    for account in accounts:
        seat = seat_map.get(account.id)
        table_stack = seat.stack if seat else 0
        current_table = table_no_map.get(seat.table_id) if seat else None

        total_chips = account.wallet_balance

        hp_list = hp_by_account.get(account.id, [])
        hands_played = len(hp_list)
        hands_won = 0
        biggest_pot_won = 0

        for hp in hp_list:
            hr = hr_map.get(hp.hand_id)
            if hr:
                try:
                    result_data = json.loads(hr.result_json)
                    awards = result_data.get("awards", {})
                    if str(hp.seat_no) in awards:
                        hands_won += 1
                        won_amount = awards[str(hp.seat_no)]
                        if isinstance(won_amount, (int, float)):
                            won_chips = int(won_amount) - hp.starting_stack
                            if won_chips > biggest_pot_won:
                                biggest_pot_won = won_chips
                except Exception:
                    pass

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

    # ── 8. Sort + slice ──────────────────────────────────────────────────────
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

    return items
