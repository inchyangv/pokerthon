"""Action validation and processing helpers."""
from __future__ import annotations

import math

from app.config import settings
from app.models.hand import Hand, HandPlayer


class ActionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def get_to_call(hand: Hand, player: HandPlayer) -> int:
    return max(0, hand.current_bet - player.round_contribution)


def get_min_raise_to(hand: Hand) -> int:
    return math.ceil(hand.current_bet * 1.5)


def validate_action(
    hand: Hand,
    player: HandPlayer,
    action_type: str,
    amount: int | None,
) -> int:
    """Validate and compute the effective amount for the action.
    Returns the effective bet amount (what goes into the pot from this action).
    Raises ActionError on invalid action.
    """
    if player.folded:
        raise ActionError("INVALID_ACTION", "Player has already folded")
    if player.all_in:
        raise ActionError("INVALID_ACTION", "Player is already all-in")
    if hand.action_seat_no != player.seat_no:
        raise ActionError("INVALID_ACTION", "Not your turn")

    stack = player.ending_stack  # current stack at time of action
    to_call = get_to_call(hand, player)

    if action_type == "FOLD":
        return 0

    elif action_type == "CHECK":
        if to_call != 0:
            raise ActionError("INVALID_ACTION", f"Cannot check: need to call {to_call}")
        return 0

    elif action_type == "CALL":
        # Auto all-in if stack < to_call
        effective = min(to_call, stack)
        return effective

    elif action_type == "BET_TO":
        if hand.current_bet > 0:
            raise ActionError("INVALID_ACTION", "Cannot BET_TO when there's already a bet; use RAISE_TO")
        if amount is None:
            raise ActionError("INVALID_ACTION", "BET_TO requires amount")
        # Total bet amount (amount is total, not incremental)
        bet = amount
        if bet < settings.BIG_BLIND and bet < stack:
            raise ActionError("INVALID_ACTION", f"Minimum bet is {settings.BIG_BLIND}")
        if bet > stack:
            raise ActionError("INVALID_ACTION", "Cannot bet more than your stack")
        return bet

    elif action_type == "RAISE_TO":
        if hand.current_bet == 0:
            raise ActionError("INVALID_ACTION", "No bet to raise; use BET_TO")
        if amount is None:
            raise ActionError("INVALID_ACTION", "RAISE_TO requires amount")
        total = amount  # total amount_to for this player
        min_raise = get_min_raise_to(hand)
        if total < min_raise and total < stack + player.round_contribution:
            raise ActionError("INVALID_ACTION", f"Minimum raise to is {min_raise}")
        if total > stack + player.round_contribution:
            raise ActionError("INVALID_ACTION", "Cannot raise more than your stack allows")
        # Incremental amount = total - already_contributed_this_round
        return total - player.round_contribution

    elif action_type == "ALL_IN":
        return stack

    else:
        raise ActionError("INVALID_ACTION", f"Unknown action type: {action_type}")
