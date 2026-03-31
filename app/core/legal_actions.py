"""Compute legal actions for a player given the current hand state."""
from __future__ import annotations

import math

from app.models.hand import Hand, HandPlayer


def get_legal_actions(hand: Hand, player: HandPlayer, big_blind: int = 2) -> list[dict]:
    """Returns list of legal actions for the player.

    big_blind should be the current table big_blind (table.big_blind).
    """
    if player.folded or player.all_in:
        return []
    if hand.action_seat_no != player.seat_no:
        return []

    stack = player.ending_stack
    to_call = max(0, hand.current_bet - player.round_contribution)
    min_raise_to = math.ceil(hand.current_bet * 1.5) if hand.current_bet > 0 else big_blind
    max_raise_to = stack + player.round_contribution  # total chips player could put in

    actions = []

    # FOLD always available on your turn
    actions.append({"type": "FOLD"})

    # CHECK
    if to_call == 0:
        actions.append({"type": "CHECK"})

    # CALL
    if to_call > 0:
        call_amount = min(to_call, stack)
        actions.append({"type": "CALL", "amount": call_amount})

    # BET_TO (only when no existing bet)
    if hand.current_bet == 0:
        if stack >= big_blind:
            actions.append({
                "type": "BET_TO",
                "min": big_blind,
                "max": stack,
            })

    # RAISE_TO (when there's an existing bet)
    if hand.current_bet > 0:
        if stack + player.round_contribution >= min_raise_to:
            actions.append({
                "type": "RAISE_TO",
                "min": min_raise_to,
                "max": max_raise_to,
            })

    # ALL_IN
    if stack > 0:
        actions.append({"type": "ALL_IN", "amount": stack})

    return actions
