"""Side pot calculator from player hand contributions."""
from __future__ import annotations

from typing import Any


def calculate_pots(players: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate main pot, side pots, and uncalled return.

    Algorithm:
    1. Sort unique contribution levels ascending.
    2. For each level, compute the pot slice = (level - prev) * num_contributing_players.
    3. If only 1 player contributed at the highest tier, that amount is the uncalled return.
    4. Otherwise, it is a real pot (main or side) with eligible_seats = non-folded contributors.

    Args:
        players: List of dicts, each with:
            - seat_no (int)
            - hand_contribution (int): total chips invested this hand
            - folded (bool): whether the player folded

    Returns:
        {
            "main_pot": int,
            "side_pots": [{"index": int, "amount": int, "eligible_seats": [int]}],
            "uncalled_return": {"seat_no": int, "amount": int} | None,
        }
    """
    # Only consider players who contributed something
    active = [p for p in players if p["hand_contribution"] > 0]
    if not active:
        return {"main_pot": 0, "side_pots": [], "uncalled_return": None}

    levels = sorted(set(p["hand_contribution"] for p in active))

    pots: list[dict[str, Any]] = []
    uncalled_return: dict[str, Any] | None = None
    prev = 0

    for level in levels:
        contributing = [p for p in active if p["hand_contribution"] >= level]
        amount = (level - prev) * len(contributing)
        eligible = [p for p in contributing if not p["folded"]]

        if len(contributing) == 1:
            # No other player reached this level — it is the uncalled portion.
            # Return to the sole contributor (even if they subsequently folded,
            # which shouldn't happen in a correctly run game).
            uncalled_return = {
                "seat_no": contributing[0]["seat_no"],
                "amount": amount,
            }
        else:
            eligible_seats = sorted(p["seat_no"] for p in eligible)
            pots.append({"amount": amount, "eligible_seats": eligible_seats})

        prev = level

    main_pot = pots[0]["amount"] if pots else 0
    side_pots = [
        {"index": i, "amount": pot["amount"], "eligible_seats": pot["eligible_seats"]}
        for i, pot in enumerate(pots[1:], 1)
    ]

    return {
        "main_pot": main_pot,
        "side_pots": side_pots,
        "uncalled_return": uncalled_return,
    }
