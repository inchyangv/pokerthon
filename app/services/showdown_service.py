"""Showdown resolution: evaluate hands, distribute pots, update stacks."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.card import Card
from app.core.evaluator import evaluate_hand
from app.core.pot_calculator import calculate_pots
from app.models.hand import Hand, HandPlayer
from app.models.table import TableSeat
from app.services.hand_service import _log_action

HAND_RANK_NAMES = {
    9: "Royal Flush",
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "One Pair",
    0: "High Card",
}


def _first_clockwise(seat_nos: list[int], after: int) -> int:
    """Return first seat_no in sorted list clockwise after *after*, wrapping cyclically."""
    seats = sorted(seat_nos)
    idx = next((i for i, s in enumerate(seats) if s > after), None)
    return seats[0] if idx is None else seats[idx]


def _distribute_pot(
    amount: int,
    eligible_seats: list[int],
    hand_evals: dict[int, tuple],
    button_seat_no: int,
) -> tuple[dict[int, int], list[int]]:
    """Find the winner(s) of *amount* chips from *eligible_seats*.

    Returns (awards_dict, winner_seat_nos).
    Ties split evenly; odd chip goes to the winner closest clockwise after the button.
    """
    if amount == 0 or not eligible_seats:
        return {}, []

    evals = {s: hand_evals[s] for s in eligible_seats if s in hand_evals}
    if not evals:
        return {}, []

    best = max(evals.values())
    winners = sorted(s for s, score in evals.items() if score == best)

    share = amount // len(winners)
    remainder = amount % len(winners)

    awards: dict[int, int] = {w: share for w in winners}
    if remainder > 0:
        odd_receiver = _first_clockwise(winners, button_seat_no)
        awards[odd_receiver] += remainder

    return awards, winners


async def resolve_showdown(session: AsyncSession, hand: Hand) -> dict[str, Any]:
    """Distribute all pots to the winner(s) and update stacks.

    Called when hand.street == 'showdown' (all-in runout, river completion, or fold win).
    Returns a result summary dict.
    """
    players_q = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = list(players_q.scalars().all())

    seats_q = await session.execute(
        select(TableSeat).where(TableSeat.table_id == hand.table_id)
    )
    seats = {s.seat_no: s for s in seats_q.scalars().all()}

    board_cards = [Card(c) for c in json.loads(hand.board_json)]
    non_folded = [p for p in players if not p.folded]

    pot_input = [
        {"seat_no": p.seat_no, "hand_contribution": p.hand_contribution, "folded": p.folded}
        for p in players
    ]
    pot_view = calculate_pots(pot_input)

    cumulative_awards: dict[int, int] = {p.seat_no: 0 for p in players}
    summaries: list[dict[str, Any]] = []

    # --- Uncalled return (always processed first, regardless of fold/showdown) ---
    if pot_view["uncalled_return"]:
        ur = pot_view["uncalled_return"]
        cumulative_awards[ur["seat_no"]] += ur["amount"]
        summaries.append({
            "type": "uncalled_return",
            "seat_no": ur["seat_no"],
            "amount": ur["amount"],
        })

    # --- Fold win: sole non-folded player takes everything ---
    if len(non_folded) == 1:
        winner = non_folded[0]
        total_pot = pot_view["main_pot"] + sum(sp["amount"] for sp in pot_view["side_pots"])
        cumulative_awards[winner.seat_no] += total_pot
        summaries.append({
            "type": "fold_win",
            "winners": [winner.seat_no],
            "amount": total_pot,
        })
        await _log_action(
            session, hand.id, "POT_AWARDED", hand.street,
            payload={"type": "fold_win", "winners": [winner.seat_no], "amount": total_pot},
        )

    else:
        # --- Full showdown: evaluate hands ---
        hand_evals: dict[int, tuple] = {}
        showdown_info: list[dict[str, Any]] = []
        for p in non_folded:
            hole = json.loads(p.hole_cards_json)
            score = evaluate_hand([Card(c) for c in hole], board_cards)
            hand_evals[p.seat_no] = score
            showdown_info.append({
                "seat_no": p.seat_no,
                "hole_cards": hole,
                "hand_rank": score[0],
                "hand_rank_name": HAND_RANK_NAMES.get(score[0], "?"),
            })

        await _log_action(
            session, hand.id, "SHOWDOWN", hand.street,
            payload={"players": showdown_info},
        )

        # Distribute main pot
        main_eligible = sorted(
            p.seat_no for p in players if not p.folded and p.hand_contribution > 0
        )
        main_awards, main_winners = _distribute_pot(
            pot_view["main_pot"], main_eligible, hand_evals, hand.button_seat_no
        )
        for seat_no, chips in main_awards.items():
            cumulative_awards[seat_no] += chips
        summaries.append({
            "type": "main_pot",
            "amount": pot_view["main_pot"],
            "winners": main_winners,
        })
        await _log_action(
            session, hand.id, "POT_AWARDED", hand.street,
            payload={"type": "main_pot", "amount": pot_view["main_pot"], "winners": main_winners},
        )

        # Distribute side pots
        for sp in pot_view["side_pots"]:
            sp_awards, sp_winners = _distribute_pot(
                sp["amount"], sp["eligible_seats"], hand_evals, hand.button_seat_no
            )
            for seat_no, chips in sp_awards.items():
                cumulative_awards[seat_no] += chips
            summaries.append({
                "type": f"side_pot_{sp['index']}",
                "index": sp["index"],
                "amount": sp["amount"],
                "winners": sp_winners,
            })
            await _log_action(
                session, hand.id, "POT_AWARDED", hand.street,
                payload={
                    "type": f"side_pot_{sp['index']}",
                    "amount": sp["amount"],
                    "winners": sp_winners,
                },
            )

    # --- Apply awards: update ending_stack and table seat stacks ---
    for p in players:
        p.ending_stack += cumulative_awards.get(p.seat_no, 0)
        if p.seat_no in seats:
            seats[p.seat_no].stack = p.ending_stack

    await session.flush()

    return {
        "pot_view": pot_view,
        "awards": {k: v for k, v in cumulative_awards.items() if v > 0},
        "summaries": summaries,
    }
