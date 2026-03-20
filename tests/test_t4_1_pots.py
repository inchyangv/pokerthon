"""Tests for side pot calculator (T4.1)."""
import pytest

from app.core.pot_calculator import calculate_pots


def mk(seat_no: int, contribution: int, folded: bool = False) -> dict:
    return {"seat_no": seat_no, "hand_contribution": contribution, "folded": folded}


def chips_in_pots(result: dict) -> int:
    return result["main_pot"] + sum(sp["amount"] for sp in result["side_pots"])


# ---------------------------------------------------------------------------
# T4.1 AC test cases
# ---------------------------------------------------------------------------


def test_two_player_simple():
    """2인 단순: main pot only, no side pots."""
    r = calculate_pots([mk(1, 20), mk(2, 20)])
    assert r["main_pot"] == 40
    assert r["side_pots"] == []
    assert r["uncalled_return"] is None


def test_three_player_equal():
    """3인 전원 동일 기여: single main pot."""
    r = calculate_pots([mk(1, 30), mk(2, 30), mk(3, 30)])
    assert r["main_pot"] == 90
    assert r["side_pots"] == []
    assert r["uncalled_return"] is None


def test_one_short_all_in():
    """3인, 1명 숏 올인: main pot + 1 side pot, no uncalled."""
    # Seat 1 all-in for 5; seats 2 and 3 each contributed 20
    r = calculate_pots([mk(1, 5), mk(2, 20), mk(3, 20)])
    assert r["main_pot"] == 15           # 5 * 3
    assert len(r["side_pots"]) == 1
    assert r["side_pots"][0]["amount"] == 30   # (20-5) * 2
    assert sorted(r["side_pots"][0]["eligible_seats"]) == [2, 3]
    assert r["uncalled_return"] is None


def test_two_all_ins_two_side_pots():
    """4인, 2명 다른 금액 올인: main pot + 2 side pots."""
    # Seat 1 all-in@10, seat 2 all-in@20, seats 3&4 each 30
    r = calculate_pots([mk(1, 10), mk(2, 20), mk(3, 30), mk(4, 30)])
    assert r["main_pot"] == 40           # 10 * 4
    assert len(r["side_pots"]) == 2
    sp1, sp2 = r["side_pots"]
    assert sp1["amount"] == 30           # (20-10) * 3
    assert sorted(sp1["eligible_seats"]) == [2, 3, 4]
    assert sp2["amount"] == 20           # (30-20) * 2
    assert sorted(sp2["eligible_seats"]) == [3, 4]
    assert r["uncalled_return"] is None


def test_uncalled_return():
    """언콜 반환: 레이즈 후 전원 폴드."""
    # SB=1 folded, BB=2 folded, raiser put in 20
    r = calculate_pots([mk(1, 1, folded=True), mk(2, 2, folded=True), mk(3, 20)])
    # Level 1:  1*3=3 → pot (2 contributing+1 folded; 3 players total), eligible=[seat3]
    assert r["main_pot"] == 3
    # Level 2:  (2-1)*2=2 → pot, eligible=[seat3]
    assert len(r["side_pots"]) == 1
    assert r["side_pots"][0]["amount"] == 2
    assert r["side_pots"][0]["eligible_seats"] == [3]
    # Level 20: (20-2)*1=18 → uncalled (only seat3 here)
    assert r["uncalled_return"] is not None
    assert r["uncalled_return"]["seat_no"] == 3
    assert r["uncalled_return"]["amount"] == 18
    # Chip conservation
    uncalled = r["uncalled_return"]["amount"]
    assert chips_in_pots(r) + uncalled == 1 + 2 + 20


def test_folded_contributions_in_pot():
    """4인, 2명 폴드, 2명 쇼다운: 폴드 기여금은 팟에 포함, eligible에서 제외."""
    r = calculate_pots([
        mk(1, 20),
        mk(2, 20, folded=True),
        mk(3, 20),
        mk(4, 20, folded=True),
    ])
    assert r["main_pot"] == 80   # 20 * 4 (folded chips still in pot)
    assert r["side_pots"] == []
    assert r["uncalled_return"] is None
    # Eligible seats are only 1 and 3 (not folded)
    # (eligible_seats not exposed for main pot in pot_view format,
    #  but we can verify via the algorithm: no side pots needed)


def test_all_in_three_contribution_tiers():
    """전원 올인 (3단계 기여 레벨): main + 1 side + uncalled return."""
    # Seat 1 all-in@10, seat 2 all-in@20, seat 3 all-in@30
    r = calculate_pots([mk(1, 10), mk(2, 20), mk(3, 30)])
    assert r["main_pot"] == 30           # 10 * 3
    assert len(r["side_pots"]) == 1
    assert r["side_pots"][0]["amount"] == 20   # (20-10) * 2
    assert sorted(r["side_pots"][0]["eligible_seats"]) == [2, 3]
    # Level 30: only seat 3 contributed → uncalled return
    assert r["uncalled_return"] is not None
    assert r["uncalled_return"]["seat_no"] == 3
    assert r["uncalled_return"]["amount"] == 10  # (30-20) * 1
    # Chip conservation
    uncalled = r["uncalled_return"]["amount"]
    assert chips_in_pots(r) + uncalled == 10 + 20 + 30


def test_chip_conservation_multiple_scenarios():
    """칩 보존 법칙: 총 팟 + 언콜 반환 = 총 기여금."""
    scenarios = [
        [mk(1, 40), mk(2, 40), mk(3, 40)],
        [mk(1, 5), mk(2, 15), mk(3, 25), mk(4, 25)],
        [mk(1, 2, folded=True), mk(2, 10), mk(3, 10)],
        [mk(1, 10), mk(2, 20, folded=True), mk(3, 30)],
        [mk(1, 1, folded=True), mk(2, 2, folded=True), mk(3, 15)],
    ]
    for players in scenarios:
        r = calculate_pots(players)
        total_contributions = sum(p["hand_contribution"] for p in players)
        uncalled = r["uncalled_return"]["amount"] if r["uncalled_return"] else 0
        assert chips_in_pots(r) + uncalled == total_contributions, (
            f"Chip conservation violated for {players}: "
            f"pots={chips_in_pots(r)} uncalled={uncalled} total={total_contributions}"
        )
