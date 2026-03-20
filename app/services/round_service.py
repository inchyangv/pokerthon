"""Betting round completion and street progression."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deck import Deck
from app.models.hand import Hand, HandAction, HandPlayer, HandStatus
from app.services.hand_service import _log_action, _next_seat

STREET_ORDER = ["preflop", "flop", "turn", "river"]
DEAL_COUNTS = {"flop": 3, "turn": 1, "river": 1}


def _is_round_complete(players: list[HandPlayer], current_bet: int) -> bool:
    """Check if all active players have matched current_bet."""
    active = [p for p in players if not p.folded and not p.all_in]

    if len(active) == 0:
        return True

    # One active player: done if they've matched current bet
    if len(active) == 1:
        return active[0].round_contribution >= current_bet

    # All active players must have matched current_bet
    return all(p.round_contribution == current_bet for p in active)


async def _all_active_acted_this_street(
    session: AsyncSession, hand: Hand, active_players: list[HandPlayer]
) -> bool:
    """Return True if every active player has made at least one non-system action this street.

    This prevents premature round completion when current_bet=0 at the start of a
    post-flop street (flop/turn/river), where all round_contributions are 0 but
    players haven't had a chance to act yet.
    """
    if not active_players:
        return True
    active_account_ids = {p.account_id for p in active_players}
    result = await session.execute(
        select(HandAction.actor_account_id)
        .where(
            HandAction.hand_id == hand.id,
            HandAction.street == hand.street,
            HandAction.is_system_action == False,  # noqa: E712
            HandAction.actor_account_id.in_(list(active_account_ids)),
        )
        .distinct()
    )
    acted_ids = set(result.scalars().all())
    return active_account_ids.issubset(acted_ids)


async def advance_street(session: AsyncSession, hand: Hand) -> bool:
    """Check if round is over; if so, advance to next street or showdown.
    Returns True if we transitioned (caller should re-evaluate state).
    Returns False if round is still in progress.
    """
    result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = list(result.scalars().all())

    # Check fold winner: only 1 non-folded player
    non_folded = [p for p in players if not p.folded]
    if len(non_folded) == 1:
        # Immediate win — handled by caller
        return True

    if not _is_round_complete(players, hand.current_bet):
        return False

    # Multi-player: ensure all active players have had a chance to act this street.
    # This prevents premature round end at start of post-flop streets (current_bet=0,
    # all round_contributions=0, but no one has acted yet).
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) >= 2:
        if not await _all_active_acted_this_street(session, hand, active):
            return False

    # Reset round contributions
    for p in players:
        p.round_contribution = 0
    hand.current_bet = 0

    # Determine next street
    current_idx = STREET_ORDER.index(hand.street)
    if current_idx >= len(STREET_ORDER) - 1:
        # After river → showdown
        hand.street = "showdown"
        hand.action_seat_no = None
        await session.commit()
        return True

    next_street = STREET_ORDER[current_idx + 1]

    # Deal board cards
    deck = Deck.from_json(hand.deck_json, hand.deal_index)
    n_cards = DEAL_COUNTS[next_street]
    new_cards = deck.deal(n_cards)
    board = json.loads(hand.board_json)
    board.extend(str(c) for c in new_cards)
    hand.board_json = json.dumps(board)
    hand.deck_json = deck.to_json()
    hand.deal_index = deck.deal_index
    hand.street = next_street

    deal_action = "DEAL_" + next_street.upper()
    await _log_action(session, hand.id, deal_action, next_street,
                      payload={"board": board})

    # Check if all-in run-out needed (0 or 1 active players)
    active = [p for p in players if not p.folded and not p.all_in]
    if len(active) <= 1:
        # Keep advancing streets until showdown
        await session.flush()
        while hand.street != "showdown" and STREET_ORDER.index(hand.street) < len(STREET_ORDER) - 1:
            await advance_street(session, hand)
        if hand.street == "river":
            hand.street = "showdown"
            hand.action_seat_no = None
        await session.commit()
        return True

    # Set first actor for new street
    # Post-flop: first active player after button
    active_seat_nos = sorted(s.seat_no for s in players if not s.folded and not s.all_in)
    if active_seat_nos:
        button = hand.button_seat_no
        first_actor = _next_seat(active_seat_nos, button)
        hand.action_seat_no = first_actor
        hand.action_deadline_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ACTION_TIMEOUT_SECONDS)
    else:
        hand.action_seat_no = None

    await session.commit()
    return True
