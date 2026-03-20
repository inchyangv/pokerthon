from types import SimpleNamespace

import pytest
from app.core.legal_actions import get_legal_actions


def make_hand(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        current_bet=kwargs.get("current_bet", 2),
        action_seat_no=kwargs.get("action_seat_no", 1),
        street=kwargs.get("street", "preflop"),
    )


def make_player(**kwargs) -> SimpleNamespace:
    return SimpleNamespace(
        seat_no=kwargs.get("seat_no", 1),
        ending_stack=kwargs.get("stack", 38),
        round_contribution=kwargs.get("round_contribution", 0),
        hand_contribution=kwargs.get("hand_contribution", 0),
        folded=kwargs.get("folded", False),
        all_in=kwargs.get("all_in", False),
    )


def action_types(actions):
    return [a["type"] for a in actions]


def test_preflop_utg():
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=38, round_contribution=0)
    actions = get_legal_actions(hand, player)
    types = action_types(actions)
    assert "FOLD" in types
    assert "CALL" in types
    assert "RAISE_TO" in types
    assert "ALL_IN" in types
    call = next(a for a in actions if a["type"] == "CALL")
    assert call["amount"] == 2


def test_bb_after_limpers():
    # BB has current_bet=2, already contributed 2, so to_call=0
    hand = make_hand(current_bet=2, action_seat_no=2)
    player = make_player(seat_no=2, stack=38, round_contribution=2)
    actions = get_legal_actions(hand, player)
    types = action_types(actions)
    assert "FOLD" in types
    assert "CHECK" in types
    assert "RAISE_TO" in types
    assert "ALL_IN" in types


def test_flop_first_action():
    hand = make_hand(current_bet=0, action_seat_no=1, street="flop")
    player = make_player(seat_no=1, stack=38, round_contribution=0)
    actions = get_legal_actions(hand, player)
    types = action_types(actions)
    assert "FOLD" in types
    assert "CHECK" in types
    assert "BET_TO" in types
    assert "ALL_IN" in types
    bet = next(a for a in actions if a["type"] == "BET_TO")
    assert bet["min"] == 2
    assert bet["max"] == 38


def test_stack_1_chip():
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=1, round_contribution=0)
    actions = get_legal_actions(hand, player)
    types = action_types(actions)
    assert "FOLD" in types
    assert "ALL_IN" in types
    assert "CALL" in types
    assert "RAISE_TO" not in types  # can't meet min raise


def test_stack_equals_to_call():
    # to_call = 2, stack = 2 → CALL goes all-in
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=2, round_contribution=0)
    actions = get_legal_actions(hand, player)
    types = action_types(actions)
    assert "FOLD" in types
    assert "CALL" in types
    assert "ALL_IN" in types
    call = next(a for a in actions if a["type"] == "CALL")
    assert call["amount"] == 2


def test_all_in_player_empty():
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=0, round_contribution=2, all_in=True)
    actions = get_legal_actions(hand, player)
    assert actions == []


def test_folded_player_empty():
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=10, round_contribution=0, folded=True)
    actions = get_legal_actions(hand, player)
    assert actions == []


def test_not_your_turn_empty():
    hand = make_hand(current_bet=2, action_seat_no=2)
    player = make_player(seat_no=1, stack=38)
    actions = get_legal_actions(hand, player)
    assert actions == []


def test_min_raise_calculations():
    # bet=2 → min_raise_to = ceil(2*1.5) = 3
    hand = make_hand(current_bet=2, action_seat_no=1)
    player = make_player(seat_no=1, stack=38, round_contribution=0)
    actions = get_legal_actions(hand, player)
    raise_a = next(a for a in actions if a["type"] == "RAISE_TO")
    assert raise_a["min"] == 3

    # bet=10 → min_raise_to = 15
    hand2 = make_hand(current_bet=10, action_seat_no=1)
    player2 = make_player(seat_no=1, stack=28, round_contribution=10)
    actions2 = get_legal_actions(hand2, player2)
    raise2 = next((a for a in actions2 if a["type"] == "RAISE_TO"), None)
    assert raise2 and raise2["min"] == 15

    # bet=17 → min_raise_to = 26
    hand3 = make_hand(current_bet=17, action_seat_no=1)
    player3 = make_player(seat_no=1, stack=21, round_contribution=17)
    actions3 = get_legal_actions(hand3, player3)
    raise3 = next((a for a in actions3 if a["type"] == "RAISE_TO"), None)
    assert raise3 and raise3["min"] == 26
