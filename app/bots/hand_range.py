"""Hand classification and range tables for preflop bot decisions."""
from __future__ import annotations

from app.core.card import RANK_MAP

RANK_ORDER = "23456789TJQKA"


def classify_hole_cards(card1: str, card2: str) -> str:
    """Return standard 2-card notation: e.g. 'AA', 'AKs', 'AKo'."""
    r1, s1 = card1[0], card1[1]
    r2, s2 = card2[0], card2[1]

    # Ensure higher rank first
    if RANK_MAP[r1] < RANK_MAP[r2]:
        r1, r2 = r2, r1
        s1, s2 = s2, s1

    if r1 == r2:
        return f"{r1}{r2}"  # Pair
    suited = s1 == s2
    suffix = "s" if suited else "o"
    return f"{r1}{r2}{suffix}"


# --- Range Tables ---
# Each range is a set of canonical hand notations (e.g. "AA", "AKs", "AKo")

def _pairs(ranks: str) -> set[str]:
    """Generate all pair combos from a rank string like 'AKQJ'."""
    return {f"{r}{r}" for r in ranks}


def _suited(high: str, low_ranks: str) -> set[str]:
    return {f"{high}{r}s" for r in low_ranks}


def _offsuit(high: str, low_ranks: str) -> set[str]:
    return {f"{high}{r}o" for r in low_ranks}


# TAG: ~15% — premium hands
TAG_RANGE: set[str] = (
    _pairs("AKQJT98")  # AA-88
    | _suited("A", "KQJT")  # AKs-ATs
    | {"KQs"}
    | _offsuit("A", "KQJ")  # AKo-AJo
)

# LAG: ~40% — TAG + speculative hands
LAG_RANGE: set[str] = (
    TAG_RANGE
    | _pairs("765432")  # 77-22
    | _suited("A", "98765432")  # A9s-A2s
    | _suited("K", "JT9")  # KJs-K9s
    | _suited("Q", "JT9")  # QJs-Q9s
    | {"JTs", "T9s", "98s", "87s", "76s"}
    | _offsuit("A", "T98")  # ATo-A8o
    | _offsuit("K", "QJT")  # KQo-KTo
)

# FISH: ~55% — LAG + weak hands
FISH_RANGE: set[str] = (
    LAG_RANGE
    | {"65s", "54s"}
    | _suited("K", "8765432")  # K8s-K2s
    | _suited("Q", "8765432")  # Q8s-Q2s
    | _offsuit("A", "765432")  # A7o-A2o
    | _offsuit("K", "J98")  # KJo-K9o
    | _offsuit("Q", "JT9")  # QJo-Q9o
    | {"J9o", "T8o"}
)

RANGES = {
    "TAG": TAG_RANGE,
    "LAG": LAG_RANGE,
    "FISH": FISH_RANGE,
}


def in_range(bot_type: str, card1: str, card2: str) -> bool:
    hand = classify_hole_cards(card1, card2)
    return hand in RANGES[bot_type]
