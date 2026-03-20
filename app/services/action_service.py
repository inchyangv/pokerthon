"""Process a player action during a hand."""
from __future__ import annotations

import json
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.action_validator import ActionError, get_to_call, validate_action
from app.models.hand import Hand, HandAction, HandPlayer
from app.models.table import TableSeat
from app.services.hand_service import _log_action, _next_seat


async def process_action(
    session: AsyncSession,
    hand: Hand,
    account_id: int,
    action_type: str,
    amount: int | None = None,
) -> HandAction:
    """Process a player action and update hand state. Returns the created HandAction."""
    # Load player
    result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id, HandPlayer.account_id == account_id)
    )
    player = result.scalar_one_or_none()
    if not player:
        raise ActionError("INVALID_ACTION", "Player not in this hand")

    # Validate
    effective_amount = validate_action(hand, player, action_type, amount)

    # Load seat for stack update
    seat_result = await session.execute(
        select(TableSeat).where(TableSeat.table_id == hand.table_id, TableSeat.seat_no == player.seat_no)
    )
    seat = seat_result.scalar_one()

    prev_current_bet = hand.current_bet
    amount_to = None

    if action_type == "FOLD":
        player.folded = True

    elif action_type == "CHECK":
        pass

    elif action_type == "CALL":
        seat.stack -= effective_amount
        player.round_contribution += effective_amount
        player.hand_contribution += effective_amount
        player.ending_stack = seat.stack
        if seat.stack == 0:
            player.all_in = True
        amount_to = player.round_contribution

    elif action_type == "BET_TO":
        # effective_amount = the total bet (BET_TO is total, not incremental)
        seat.stack -= effective_amount
        player.round_contribution += effective_amount
        player.hand_contribution += effective_amount
        player.ending_stack = seat.stack
        hand.current_bet = player.round_contribution
        amount_to = player.round_contribution
        if seat.stack == 0:
            player.all_in = True

    elif action_type == "RAISE_TO":
        # effective_amount = incremental amount added this action
        seat.stack -= effective_amount
        player.round_contribution += effective_amount
        player.hand_contribution += effective_amount
        player.ending_stack = seat.stack
        hand.current_bet = player.round_contribution
        amount_to = player.round_contribution
        if seat.stack == 0:
            player.all_in = True

    elif action_type == "ALL_IN":
        all_in_amount = effective_amount  # = stack
        seat.stack -= all_in_amount
        player.round_contribution += all_in_amount
        player.hand_contribution += all_in_amount
        player.ending_stack = seat.stack
        player.all_in = True
        if player.round_contribution > hand.current_bet:
            hand.current_bet = player.round_contribution
        amount_to = player.round_contribution

    # Log action
    action = await _log_action(
        session, hand.id, action_type, hand.street,
        actor_account_id=account_id,
        actor_seat_no=player.seat_no,
        amount=effective_amount if effective_amount else None,
        amount_to=amount_to,
        is_system=False,
    )

    await session.flush()

    # Check round completion / street advancement
    from app.services.round_service import advance_street
    advanced = await advance_street(session, hand)
    if not advanced:
        # Round still in progress; just advance the action seat
        await _advance_action(session, hand)
    else:
        # Transition occurred; resolve showdown if hand has reached that state
        await session.refresh(hand)
        if hand.street == "showdown":
            from app.services.showdown_service import resolve_showdown
            await resolve_showdown(session, hand)

    await session.commit()
    return action


async def _advance_action(session: AsyncSession, hand: Hand) -> None:
    """Move hand.action_seat_no to next eligible player."""
    result = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand.id)
    )
    players = {p.seat_no: p for p in result.scalars().all()}
    active_seats = sorted(
        s for s, p in players.items() if not p.folded and not p.all_in
    )
    if not active_seats:
        hand.action_seat_no = None
        return
    current = hand.action_seat_no
    next_seat = _next_seat(active_seats, current)
    hand.action_seat_no = next_seat

    from datetime import datetime, timedelta, timezone
    from app.config import settings
    hand.action_deadline_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ACTION_TIMEOUT_SECONDS)
