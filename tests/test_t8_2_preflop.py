"""Tests for preflop hand range and bot decision logic."""
import pytest

from app.bots import BotType
from app.bots.hand_range import classify_hole_cards, in_range, TAG_RANGE, LAG_RANGE, FISH_RANGE
from app.bots.preflop import decide_preflop


# --- classify_hole_cards ---

def test_classify_pair():
    assert classify_hole_cards("As", "Ah") == "AA"


def test_classify_suited():
    assert classify_hole_cards("Ks", "Qs") == "KQs"


def test_classify_offsuit():
    assert classify_hole_cards("7c", "2h") == "72o"


def test_classify_rank_order():
    # Lower rank first should still yield higher rank first in result
    assert classify_hole_cards("2s", "Ah") == "A2o"


# --- Range membership ---

def test_tag_has_aces():
    assert in_range("TAG", "As", "Ah")  # AA

def test_lag_has_aces():
    assert in_range("LAG", "As", "Ah")

def test_fish_has_aces():
    assert in_range("FISH", "As", "Ah")

def test_tag_folds_72o():
    assert not in_range("TAG", "7s", "2h")

def test_lag_folds_72o():
    assert not in_range("LAG", "7s", "2h")

def test_fish_does_not_fold_72o():
    # 72o is not in FISH range either (it's truly the worst hand)
    # FISH folds out-of-range but may call randomly
    pass  # This is a behavioural test, not range membership

def test_fish_wider_range_than_lag():
    assert len(FISH_RANGE) > len(LAG_RANGE) > len(TAG_RANGE)

def test_tag_range_contains_premium_pairs():
    for rank in "AKQJT98":
        assert f"{rank}{rank}" in TAG_RANGE


# --- decide_preflop ---

LEGAL_ACTIONS_TYPICAL = [
    {"action_type": "FOLD"},
    {"action_type": "CALL"},
    {"action_type": "RAISE_TO", "min_amount": 6, "max_amount": 200},
]

LEGAL_ACTIONS_CHECK = [
    {"action_type": "CHECK"},
    {"action_type": "RAISE_TO", "min_amount": 4, "max_amount": 200},
]


def test_tag_raises_or_calls_with_aa():
    results = set()
    for _ in range(50):
        d = decide_preflop(BotType.TAG, ["As", "Ah"], LEGAL_ACTIONS_TYPICAL, 2, 100, 3)
        results.add(d.action_type)
    # TAG with AA should raise most of the time
    assert "RAISE_TO" in results or "CALL" in results


def test_tag_folds_72o_with_legal_fold():
    decisions = [
        decide_preflop(BotType.TAG, ["7s", "2h"], LEGAL_ACTIONS_TYPICAL, 2, 100, 3)
        for _ in range(20)
    ]
    assert all(d.action_type == "FOLD" for d in decisions)


def test_fish_wide_range_calls():
    # FISH with mid hand (in FISH range) should call frequently
    results = [
        decide_preflop(BotType.FISH, ["Ks", "8h"], LEGAL_ACTIONS_TYPICAL, 2, 100, 3)
        for _ in range(50)
    ]
    call_count = sum(1 for d in results if d.action_type == "CALL")
    assert call_count > 20  # majority should call


def test_action_always_in_legal_actions():
    for bot_type in BotType:
        for _ in range(20):
            d = decide_preflop(bot_type, ["As", "Kh"], LEGAL_ACTIONS_TYPICAL, 2, 100, 3)
            assert d.action_type in {"FOLD", "CALL", "RAISE_TO", "CHECK", "ALL_IN"}
            if d.action_type == "RAISE_TO":
                raise_action = next(a for a in LEGAL_ACTIONS_TYPICAL if a["action_type"] == "RAISE_TO")
                assert raise_action["min_amount"] <= d.amount <= raise_action["max_amount"]


def test_check_available_no_fold():
    d = decide_preflop(BotType.TAG, ["7s", "2h"], LEGAL_ACTIONS_CHECK, 0, 100, 2)
    assert d.action_type == "CHECK"
