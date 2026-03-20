import pytest
from app.core.card import Card
from app.core.deck import Deck
from app.core.evaluator import evaluate_hand, compare_hands


def cards(*strs):
    return [Card(s) for s in strs]


def test_royal_flush():
    hole = cards("As", "Ks")
    board = cards("Qs", "Js", "Ts", "2h", "3d")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 9


def test_straight_flush():
    hole = cards("9s", "8s")
    board = cards("7s", "6s", "5s", "2h", "3d")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 8
    assert tb[0] == 7  # 9-high straight flush (9=index 7)


def test_four_of_a_kind():
    hole = cards("As", "Ah")
    board = cards("Ad", "Ac", "Kh", "2d", "3s")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 7
    assert tb[0] == 12  # Ace


def test_full_house():
    hole = cards("As", "Ah")
    board = cards("Ad", "Kh", "Kd", "2c", "3s")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 6
    assert tb[0] == 12  # trip aces
    assert tb[1] == 11  # pair kings


def test_flush():
    hole = cards("As", "Ks")
    board = cards("9s", "7s", "3s", "2h", "4d")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 5


def test_straight_normal():
    hole = cards("9h", "8d")
    board = cards("7s", "6c", "5h", "2d", "As")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 4
    assert tb[0] == 7  # 9-high


def test_straight_wheel():
    hole = cards("Ah", "2d")
    board = cards("3s", "4c", "5h", "Kd", "Qs")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 4
    assert tb[0] == 3  # 5-high straight (index 3)


def test_three_of_a_kind():
    hole = cards("As", "Ah")
    board = cards("Ad", "2h", "3c", "7d", "9s")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 3


def test_two_pair():
    hole = cards("As", "Ah")
    board = cards("Kh", "Kd", "2c", "7s", "8d")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 2
    assert tb[0] == 12  # aces
    assert tb[1] == 11  # kings


def test_one_pair():
    hole = cards("As", "Ah")
    board = cards("2h", "3d", "7c", "9s", "Kd")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 1


def test_high_card():
    hole = cards("As", "Kh")
    board = cards("2d", "3c", "7s", "9h", "Jd")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 0
    assert tb[0] == 12  # Ace high


def test_best_5_from_7():
    # 7 cards, best 5 should pick flush
    hole = cards("As", "Ks")
    board = cards("Qs", "Js", "9s", "2h", "3d")
    rank, tb = evaluate_hand(hole, board)
    assert rank == 5  # flush (not royal — only 4 to broadway)


def test_tiebreaker_comparison():
    hand_a = evaluate_hand(cards("As", "Kh"), cards("2d", "3c", "7s", "9h", "Jd"))
    hand_b = evaluate_hand(cards("Qs", "Kd"), cards("2h", "3s", "7c", "9d", "Jh"))
    result = compare_hands(hand_a, hand_b)
    assert result == 1  # Ace > Queen high card


def test_split_pot():
    hand_a = evaluate_hand(cards("As", "Ks"), cards("Qd", "Jh", "Tc", "2d", "3s"))
    hand_b = evaluate_hand(cards("Ah", "Kd"), cards("Qd", "Jh", "Tc", "2d", "3s"))
    result = compare_hands(hand_a, hand_b)
    assert result == 0  # tie


def test_wheel_vs_six_high_straight():
    # wheel (A-2-3-4-5) should lose to 6-high (2-3-4-5-6)
    wheel = evaluate_hand(cards("Ah", "2d"), cards("3s", "4c", "5h", "Kd", "Qs"))
    six_high = evaluate_hand(cards("2h", "3d"), cards("4s", "5c", "6h", "Kd", "Qs"))
    assert compare_hands(wheel, six_high) == -1


def test_flush_beats_straight():
    straight = evaluate_hand(cards("9h", "8d"), cards("7s", "6c", "5h", "2d", "As"))
    flush = evaluate_hand(cards("As", "Ks"), cards("9s", "7s", "3s", "2h", "4d"))
    assert compare_hands(flush, straight) == 1


def test_deck_deal_and_restore():
    d = Deck()
    d.shuffle()
    json_str = d.to_json()
    idx = d.deal_index
    dealt = d.deal(5)

    d2 = Deck.from_json(json_str, idx)
    dealt2 = d2.deal(5)
    assert [str(c) for c in dealt] == [str(c) for c in dealt2]
