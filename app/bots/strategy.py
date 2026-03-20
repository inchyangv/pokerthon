"""Unified bot strategy interface: routes preflop vs postflop decisions."""
from __future__ import annotations

from dataclasses import dataclass

from app.bots import BotType
from app.bots.postflop import PostflopDecision, decide_postflop
from app.bots.preflop import PreflopDecision, decide_preflop


@dataclass
class BotDecision:
    action_type: str
    amount: int | None = None


def decide(
    bot_type: BotType,
    street: str,
    hole_cards: list[str],
    board: list[str],
    legal_actions: list[dict],
    current_bet: int,
    to_call: int,
    stack: int,
    pot_size: int,
) -> BotDecision:
    """Return a valid bot decision, falling back to FOLD/CHECK if invalid."""
    legal_types = {a["action_type"] for a in legal_actions}

    if street == "preflop":
        raw = decide_preflop(bot_type, hole_cards, legal_actions, current_bet, stack, pot_size)
    else:
        raw = decide_postflop(
            bot_type, hole_cards, board, legal_actions, current_bet, to_call, stack, pot_size
        )

    # Validate result is within legal actions
    if raw.action_type in legal_types:
        if raw.action_type in ("RAISE_TO", "BET") and raw.amount is not None:
            for a in legal_actions:
                if a["action_type"] == raw.action_type:
                    min_a = a.get("min_amount", 1)
                    max_a = a.get("max_amount", stack)
                    amount = max(min_a, min(max_a, raw.amount))
                    return BotDecision(raw.action_type, amount)
        return BotDecision(raw.action_type, raw.amount)

    # Fallback
    if "CHECK" in legal_types:
        return BotDecision("CHECK")
    return BotDecision("FOLD")
