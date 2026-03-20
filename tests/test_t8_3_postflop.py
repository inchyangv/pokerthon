"""Tests for postflop decision engine and strategy interface."""
import pytest

from app.bots import BotType
from app.bots.hand_strength import calculate_pot_odds, evaluate_hand_strength
from app.bots.postflop import decide_postflop
from app.bots.strategy import decide


LEGAL_WITH_BET = [
    {"action_type": "CHECK"},
    {"action_type": "RAISE_TO", "min_amount": 4, "max_amount": 200},
]

LEGAL_WITH_CALL = [
    {"action_type": "FOLD"},
    {"action_type": "CALL"},
    {"action_type": "RAISE_TO", "min_amount": 8, "max_amount": 200},
]

BOARD_FLOP = ["Ah", "Kd", "7c"]
BOARD_RIVER = ["Ah", "Kd", "7c", "2s", "9h"]

# Flush (hearts): As, Ks hole + Ah, Kd, 7c, 2s, 9h board
# Best: As Ah 9h Kd 7c → flush with As, Ks, Ah, 9h...
# Actually let's use a full-house hand: Ah, Ad + board Ac, As, Kh = AAAK full house
BOARD_STRONG_RIVER = ["Ac", "Ah", "Kh", "2s", "9h"]  # board
STRONG_HOLE = ["As", "Ad"]   # As, Ad + board Ac, Ah, Kh, 2s, 9h → Four aces! rank 7

WEAK_HOLE = ["2h", "3c"]


# --- hand strength ---

def test_strength_range():
    s = evaluate_hand_strength(STRONG_HOLE, BOARD_FLOP)
    assert 0.0 <= s <= 1.0


def test_strength_strong_hand():
    # Four aces → rank 7 → 7/9 * 0.93 ≈ 0.72
    s = evaluate_hand_strength(STRONG_HOLE, BOARD_STRONG_RIVER)
    assert s >= 0.6


def test_strength_flop_discounted():
    s_flop = evaluate_hand_strength(STRONG_HOLE, BOARD_FLOP)
    s_river = evaluate_hand_strength(STRONG_HOLE, BOARD_STRONG_RIVER)
    # Flop (3 cards) gets 0.85 discount; river (5 cards) gets no discount
    # With strong hand, river score should be higher
    assert s_flop < s_river


def test_pot_odds_zero_call():
    assert calculate_pot_odds(0, 100) == 0.0


def test_pot_odds_calculation():
    odds = calculate_pot_odds(20, 80)
    assert abs(odds - 0.2) < 0.001


# --- postflop decisions ---

def test_tag_bets_strong_hand():
    # Four aces → high strength → TAG should bet
    results = [
        decide_postflop(BotType.TAG, STRONG_HOLE, BOARD_STRONG_RIVER, LEGAL_WITH_BET, 0, 0, 200, 50)
        for _ in range(30)
    ]
    bet_raises = [r for r in results if r.action_type in ("RAISE_TO", "BET")]
    assert len(bet_raises) > 15  # Most should bet with four of a kind


def test_fish_calls_weak_hand():
    results = [
        decide_postflop(BotType.FISH, WEAK_HOLE, BOARD_RIVER, LEGAL_WITH_CALL, 10, 10, 200, 50)
        for _ in range(50)
    ]
    calls = [r for r in results if r.action_type == "CALL"]
    # FISH should call weak hands at least 30% of the time
    assert len(calls) >= 10


# --- strategy interface ---

def test_strategy_preflop_routes():
    d = decide(BotType.TAG, "preflop", ["As", "Ah"], [], LEGAL_WITH_BET, 2, 2, 200, 4)
    assert d.action_type in {"FOLD", "CHECK", "CALL", "RAISE_TO", "ALL_IN"}


def test_strategy_postflop_routes():
    d = decide(BotType.LAG, "flop", WEAK_HOLE, BOARD_FLOP, LEGAL_WITH_CALL, 10, 10, 200, 40)
    assert d.action_type in {"FOLD", "CHECK", "CALL", "RAISE_TO", "BET", "ALL_IN"}


def test_strategy_raise_amount_clamped():
    legal = [
        {"action_type": "FOLD"},
        {"action_type": "CALL"},
        {"action_type": "RAISE_TO", "min_amount": 10, "max_amount": 100},
    ]
    for _ in range(20):
        d = decide(BotType.LAG, "river", STRONG_HOLE, BOARD_STRONG_RIVER, legal, 10, 5, 100, 50)
        if d.action_type == "RAISE_TO":
            assert 10 <= d.amount <= 100


def test_strategy_fallback_to_check():
    # Only CHECK available, decision should return CHECK even for TAG w/ weak hand
    d = decide(BotType.TAG, "river", WEAK_HOLE, BOARD_RIVER, [{"action_type": "CHECK"}], 0, 0, 200, 50)
    assert d.action_type == "CHECK"


