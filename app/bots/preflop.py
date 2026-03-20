"""Preflop decision logic for bot types."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.bots import BotType
from app.bots.hand_range import in_range
from app.config import settings


@dataclass
class PreflopDecision:
    action_type: str  # FOLD, CHECK, CALL, RAISE_TO, ALL_IN
    amount: int | None = None


def decide_preflop(
    bot_type: BotType,
    hole_cards: list[str],
    legal_actions: list[dict],
    current_bet: int,
    stack: int,
    pot_size: int,
) -> PreflopDecision:
    """Decide preflop action based on bot type and hand range."""
    card1, card2 = hole_cards[0], hole_cards[1]
    legal_types = {a["action_type"] for a in legal_actions}
    bb = settings.BIG_BLIND

    def _get_action(action_type: str) -> dict | None:
        for a in legal_actions:
            if a["action_type"] == action_type:
                return a
        return None

    def _raise_amount(multiplier: float) -> int:
        base = int(bb * multiplier)
        # Ensure within legal raise bounds
        raise_action = _get_action("RAISE_TO")
        if raise_action:
            min_r = raise_action.get("min_amount", base)
            max_r = raise_action.get("max_amount", stack)
            return max(min_r, min(max_r, base))
        return base

    # FISH: even out-of-range hands get a chance to call
    if bot_type == BotType.FISH:
        if not in_range(BotType.FISH.value, card1, card2):
            # 25% chance to call anyway
            if random.random() < 0.25 and "CALL" in legal_types:
                return PreflopDecision("CALL")
            if "CHECK" in legal_types:
                return PreflopDecision("CHECK")
            return PreflopDecision("FOLD")
        # FISH in range: call-heavy
        roll = random.random()
        if roll < 0.20 and "RAISE_TO" in legal_types:
            return PreflopDecision("RAISE_TO", _raise_amount(bb * 2))  # min-raise
        elif roll < 0.95 and "CALL" in legal_types:
            return PreflopDecision("CALL")
        elif "CHECK" in legal_types:
            return PreflopDecision("CHECK")
        elif "CALL" in legal_types:
            return PreflopDecision("CALL")
        return PreflopDecision("FOLD")

    # TAG / LAG: fold out-of-range hands
    if not in_range(bot_type.value, card1, card2):
        if "CHECK" in legal_types:
            return PreflopDecision("CHECK")
        return PreflopDecision("FOLD")

    if bot_type == BotType.TAG:
        roll = random.random()
        if roll < 0.70 and "RAISE_TO" in legal_types:
            mult = random.uniform(2.5, 3.5)
            return PreflopDecision("RAISE_TO", _raise_amount(mult))
        elif "CALL" in legal_types:
            return PreflopDecision("CALL")
        elif "CHECK" in legal_types:
            return PreflopDecision("CHECK")
        return PreflopDecision("FOLD")

    # LAG
    roll = random.random()
    if roll < 0.05 and "ALL_IN" in legal_types:
        return PreflopDecision("ALL_IN")
    elif roll < 0.85 and "RAISE_TO" in legal_types:
        mult = random.uniform(2.5, 3.5)
        return PreflopDecision("RAISE_TO", _raise_amount(mult))
    elif "CALL" in legal_types:
        return PreflopDecision("CALL")
    elif "CHECK" in legal_types:
        return PreflopDecision("CHECK")
    return PreflopDecision("FOLD")
