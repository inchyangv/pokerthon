from __future__ import annotations

import json
import random

from app.core.card import Card, RANK_ORDER, SUITS

_EXPECTED_DECK_SIZE = 52
_rng = random.SystemRandom()


class Deck:
    def __init__(self, cards: list[Card] | None = None):
        if cards is not None:
            strs = [str(c) for c in cards]
            if len(strs) != _EXPECTED_DECK_SIZE or len(set(strs)) != _EXPECTED_DECK_SIZE:
                raise ValueError(
                    f"Deck integrity error: expected {_EXPECTED_DECK_SIZE} unique cards, "
                    f"got {len(strs)} with {len(set(strs))} unique"
                )
            self._cards = list(cards)
        else:
            self._cards = [Card(r + s) for r in RANK_ORDER for s in "shdc"]
        self.deal_index = 0

    def shuffle(self) -> None:
        _rng.shuffle(self._cards)
        self.deal_index = 0

    def deal(self, n: int) -> list[Card]:
        if self.deal_index + n > len(self._cards):
            raise ValueError("Not enough cards in deck")
        cards = self._cards[self.deal_index: self.deal_index + n]
        self.deal_index += n
        return cards

    def to_json(self) -> str:
        return json.dumps([str(c) for c in self._cards])

    @classmethod
    def from_json(cls, data: str, deal_index: int = 0) -> "Deck":
        raw = json.loads(data)
        if len(raw) != _EXPECTED_DECK_SIZE or len(set(raw)) != _EXPECTED_DECK_SIZE:
            raise ValueError(
                f"Deck integrity error: expected {_EXPECTED_DECK_SIZE} unique cards in stored deck, "
                f"got {len(raw)} with {len(set(raw))} unique"
            )
        cards = [Card(s) for s in raw]
        d = cls(cards)
        d.deal_index = deal_index
        return d

    def __len__(self) -> int:
        return len(self._cards) - self.deal_index
