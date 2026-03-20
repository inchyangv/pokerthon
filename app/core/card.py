from __future__ import annotations

RANK_ORDER = "23456789TJQKA"
RANK_MAP = {r: i for i, r in enumerate(RANK_ORDER)}
SUITS = frozenset("shdc")


class Card:
    __slots__ = ("rank", "suit", "_str")

    def __init__(self, s: str):
        if len(s) != 2 or s[0] not in RANK_MAP or s[1] not in SUITS:
            raise ValueError(f"Invalid card: {s!r}")
        self.rank = s[0]
        self.suit = s[1]
        self._str = s

    @property
    def rank_value(self) -> int:
        return RANK_MAP[self.rank]

    def __str__(self) -> str:
        return self._str

    def __repr__(self) -> str:
        return f"Card({self._str!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Card) and self._str == other._str

    def __hash__(self) -> int:
        return hash(self._str)
