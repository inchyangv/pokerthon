"""Postflop decision logic for bot types."""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.bots import BotType
from app.bots.hand_strength import calculate_pot_odds, evaluate_hand_strength


@dataclass
class PostflopDecision:
    action_type: str  # FOLD, CHECK, CALL, RAISE_TO, BET, ALL_IN
    amount: int | None = None


def decide_postflop(
    bot_type: BotType,
    hole_cards: list[str],
    board: list[str],
    legal_actions: list[dict],
    current_bet: int,
    to_call: int,
    stack: int,
    pot_size: int,
) -> PostflopDecision:
    strength = evaluate_hand_strength(hole_cards, board)
    pot_odds = calculate_pot_odds(to_call, pot_size)
    legal_types = {a["action_type"] for a in legal_actions}

    def _get(action_type: str) -> dict | None:
        for a in legal_actions:
            if a["action_type"] == action_type:
                return a
        return None

    def _bet_amount(fraction: float) -> int:
        amount = max(1, int(pot_size * fraction))
        # Clamp to legal bounds
        for at in ("RAISE_TO", "BET"):
            action = _get(at)
            if action:
                min_a = action.get("min_amount", 1)
                max_a = action.get("max_amount", stack)
                return max(min_a, min(max_a, amount))
        return amount

    def _can_bet() -> bool:
        return "RAISE_TO" in legal_types or "BET" in legal_types

    def _bet_action(fraction: float) -> PostflopDecision:
        amt = _bet_amount(fraction)
        if "RAISE_TO" in legal_types:
            return PostflopDecision("RAISE_TO", amt)
        return PostflopDecision("BET", amt)

    if bot_type == BotType.TAG:
        bluff = random.random() < 0.05
        if strength >= 0.7 or bluff:
            if _can_bet():
                return _bet_action(random.uniform(0.6, 0.8))
            elif "CALL" in legal_types:
                return PostflopDecision("CALL")
            return PostflopDecision("CHECK")
        elif strength >= 0.4:
            if "CHECK" in legal_types:
                return PostflopDecision("CHECK")
            elif "CALL" in legal_types and strength > pot_odds:
                return PostflopDecision("CALL")
            return PostflopDecision("FOLD")
        else:
            if "CHECK" in legal_types:
                return PostflopDecision("CHECK")
            return PostflopDecision("FOLD")

    elif bot_type == BotType.LAG:
        bluff = random.random() < 0.25
        if strength >= 0.6 or bluff:
            if _can_bet():
                return _bet_action(random.uniform(0.7, 1.0))
            elif "CALL" in legal_types:
                return PostflopDecision("CALL")
            return PostflopDecision("CHECK")
        elif strength >= 0.3:
            if random.random() < 0.5:
                if _can_bet():
                    return _bet_action(0.5)
                elif "CALL" in legal_types:
                    return PostflopDecision("CALL")
            elif "CALL" in legal_types:
                return PostflopDecision("CALL")
            if "CHECK" in legal_types:
                return PostflopDecision("CHECK")
            return PostflopDecision("FOLD")
        else:
            if random.random() < 0.25 and _can_bet():
                return _bet_action(0.75)
            if "CHECK" in legal_types:
                return PostflopDecision("CHECK")
            return PostflopDecision("FOLD")

    else:  # FISH
        if strength >= 0.7:
            roll = random.random()
            if roll < 0.20 and _can_bet():
                return _bet_action(random.uniform(0.5, 0.8))
            elif "CALL" in legal_types:
                return PostflopDecision("CALL")
            return PostflopDecision("CHECK")
        elif strength >= 0.3:
            roll = random.random()
            if roll < 0.70 and "CALL" in legal_types:
                return PostflopDecision("CALL")
            elif roll < 0.90:
                if "CHECK" in legal_types:
                    return PostflopDecision("CHECK")
            return PostflopDecision("FOLD")
        else:
            roll = random.random()
            if roll < 0.40 and "CALL" in legal_types:
                return PostflopDecision("CALL")
            elif roll < 0.70:
                if "CHECK" in legal_types:
                    return PostflopDecision("CHECK")
            return PostflopDecision("FOLD")
