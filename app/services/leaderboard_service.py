"""Leaderboard statistics aggregation."""
from __future__ import annotations

import json
from datetime import datetime, timezone

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
    # Load all accounts
    query = select(Account)
    if not include_bots:
        query = query.where(Account.is_bot == False)  # noqa: E712
    result = await session.execute(query)
    accounts = list(result.scalars().all())

    items = []
    for account in accounts:
        # Current seat (table_stack, current_table)
        seat_result = await session.execute(
            select(TableSeat).where(
                TableSeat.account_id == account.id,
                TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
            )
        )
        seat = seat_result.scalar_one_or_none()
        table_stack = 0
        current_table = None
        if seat:
            table_stack = seat.stack
            table_result = await session.execute(
                select(Table).where(Table.id == seat.table_id)
            )
            table = table_result.scalar_one()
            current_table = table.table_no

        total_chips = account.wallet_balance

        # Hands played (FINISHED hands only)
        hp_result = await session.execute(
            select(HandPlayer).where(HandPlayer.account_id == account.id).join(
                Hand, Hand.id == HandPlayer.hand_id
            ).where(Hand.status == HandStatus.FINISHED)
        )
        hp_list = list(hp_result.scalars().all())
        hands_played = len(hp_list)

        # Hands won (check HandResult awards)
        hands_won = 0
        biggest_pot_won = 0
        for hp in hp_list:
            hand_result = await session.execute(
                select(HandResult).where(HandResult.hand_id == hp.hand_id)
            )
            hr = hand_result.scalar_one_or_none()
            if hr:
                try:
                    result_data = json.loads(hr.result_json)
                    awards = result_data.get("awards", {})
                    # awards keys are seat_no strings
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

        # Total profit = current chips - all ADMIN_GRANT received
        grant_result = await session.execute(
            select(ChipLedger).where(
                ChipLedger.account_id == account.id,
                ChipLedger.reason_type == LedgerReasonType.ADMIN_GRANT,
            )
        )
        total_granted = sum(g.delta for g in grant_result.scalars().all())
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

    # Sort
    sort_key_map = {
        "chips": lambda x: -x["total_chips"],
        "profit": lambda x: -x["total_profit"],
        "win_rate": lambda x: (-x["win_rate"], -x["hands_played"]),
        "hands_played": lambda x: -x["hands_played"],
    }
    key_fn = sort_key_map.get(sort_by, sort_key_map["chips"])
    items.sort(key=key_fn)
    items = items[:limit]

    # Add rank
    for i, item in enumerate(items, 1):
        item["rank"] = i

    return items
