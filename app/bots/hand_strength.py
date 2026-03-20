"""Hand strength evaluation wrapper for bot strategy."""
from __future__ import annotations

from app.core.card import Card
from app.core.evaluator import evaluate_hand


def evaluate_hand_strength(hole_cards: list[str], board: list[str]) -> float:
    """Return normalized hand strength 0.0–1.0 based on best hand rank.

    Adjusts for board uncertainty: fewer board cards = lower weight on rank.
    """
    hole = [Card(c) for c in hole_cards]
    board_cards = [Card(c) for c in board]

    if len(board_cards) < 3:
        # Pre-board: can't really evaluate — return 0.5 placeholder
        return 0.5

    hand_rank, _ = evaluate_hand(hole, board_cards)
    # hand_rank is 0–9; normalize to 0.0–1.0
    raw_score = hand_rank / 9.0

    # Apply uncertainty discount on flop (3 cards): more cards to come
    board_count = len(board_cards)
    if board_count == 3:  # flop
        return raw_score * 0.85
    elif board_count == 4:  # turn
        return raw_score * 0.93
    # river: full confidence
    return raw_score


def calculate_pot_odds(to_call: int, pot_size: int) -> float:
    """Return the fraction of the final pot represented by the call."""
    if to_call <= 0:
        return 0.0
    return to_call / (pot_size + to_call)
