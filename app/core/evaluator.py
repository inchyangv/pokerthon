"""7-card Texas Hold'em hand evaluator.

Hand ranks (higher = better):
  9 = Royal Flush
  8 = Straight Flush
  7 = Four of a Kind
  6 = Full House
  5 = Flush
  4 = Straight
  3 = Three of a Kind
  2 = Two Pair
  1 = One Pair
  0 = High Card

Returns (hand_rank, tiebreakers) where tiebreakers is a tuple of ints for comparison.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from app.core.card import Card, RANK_MAP


def _rank_val(r: str) -> int:
    return RANK_MAP[r]


def _evaluate_5(cards: list[Card]) -> tuple[int, tuple]:
    ranks = sorted([c.rank_value for c in cards], reverse=True)
    suits = [c.suit for c in cards]
    is_flush = len(set(suits)) == 1

    # Check straight (including wheel A-2-3-4-5)
    is_straight, straight_high = _check_straight(ranks)

    if is_flush and is_straight:
        return (9 if straight_high == 12 else 8), (straight_high,)

    counts = Counter(c.rank for c in cards)
    freq = sorted(counts.values(), reverse=True)
    groups = sorted(counts.keys(), key=lambda r: (counts[r], _rank_val(r)), reverse=True)

    if freq[0] == 4:
        quad_rank = groups[0]
        kicker = groups[1]
        return 7, (_rank_val(quad_rank), _rank_val(kicker))

    if freq[0] == 3 and freq[1] == 2:
        trip_rank = groups[0]
        pair_rank = groups[1]
        return 6, (_rank_val(trip_rank), _rank_val(pair_rank))

    if is_flush:
        return 5, tuple(ranks)

    if is_straight:
        return 4, (straight_high,)

    if freq[0] == 3:
        trip_rank = groups[0]
        kickers = sorted([_rank_val(r) for r in groups[1:]], reverse=True)
        return 3, (_rank_val(trip_rank),) + tuple(kickers)

    if freq[0] == 2 and freq[1] == 2:
        pair1, pair2 = groups[0], groups[1]
        kicker = groups[2]
        return 2, (_rank_val(pair1), _rank_val(pair2), _rank_val(kicker))

    if freq[0] == 2:
        pair_rank = groups[0]
        kickers = sorted([_rank_val(r) for r in groups[1:]], reverse=True)
        return 1, (_rank_val(pair_rank),) + tuple(kickers)

    return 0, tuple(ranks)


def _check_straight(sorted_desc_ranks: list[int]) -> tuple[bool, int]:
    unique = sorted(set(sorted_desc_ranks), reverse=True)
    # Normal straight
    for i in range(len(unique) - 4):
        window = unique[i: i + 5]
        if window[0] - window[4] == 4 and len(set(window)) == 5:
            return True, window[0]
    # Wheel: A-2-3-4-5 → ranks 12,3,2,1,0
    if set(unique) >= {12, 3, 2, 1, 0}:
        return True, 3  # high card is 5 (index 3)
    return False, 0


def evaluate_hand(hole_cards: list[Card], board_cards: list[Card]) -> tuple[int, tuple]:
    """Evaluate the best 5-card hand from 7 cards. Returns (hand_rank, tiebreakers)."""
    all_cards = hole_cards + board_cards
    assert 5 <= len(all_cards) <= 7
    best = None
    for combo in combinations(all_cards, 5):
        score = _evaluate_5(list(combo))
        if best is None or score > best:
            best = score
    return best


def compare_hands(
    hand_a: tuple[int, tuple],
    hand_b: tuple[int, tuple],
) -> int:
    """Returns 1 if a wins, -1 if b wins, 0 if tie."""
    if hand_a > hand_b:
        return 1
    if hand_a < hand_b:
        return -1
    return 0
