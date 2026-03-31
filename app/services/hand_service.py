"""Hand initialization: button rotation, blinds, dealing, first action."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.card import Card
from app.core.deck import Deck
from app.models.hand import Hand, HandAction, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat


async def get_active_hand(session: AsyncSession, table_id: int) -> Hand | None:
    result = await session.execute(
        select(Hand)
        .where(Hand.table_id == table_id, Hand.status == HandStatus.IN_PROGRESS)
        .order_by(Hand.id.desc())
    )
    hands = list(result.scalars().all())
    if not hands:
        return None
    # If multiple active hands exist (shouldn't happen), cancel extras
    if len(hands) > 1:
        import logging
        logging.getLogger(__name__).warning(
            "Multiple active hands for table_id=%d, cancelling duplicates", table_id
        )
        for extra in hands[1:]:
            extra.status = HandStatus.FINISHED
        await session.commit()
    return hands[0]


async def _next_seq(session: AsyncSession, hand_id: int) -> int:
    result = await session.execute(
        select(HandAction).where(HandAction.hand_id == hand_id).order_by(HandAction.seq.desc())
    )
    last = result.scalars().first()
    return (last.seq + 1) if last else 1


async def _log_action(
    session: AsyncSession,
    hand_id: int,
    action_type: str,
    street: str | None = None,
    actor_account_id: int | None = None,
    actor_seat_no: int | None = None,
    amount: int | None = None,
    amount_to: int | None = None,
    payload: dict | None = None,
    is_system: bool = True,
) -> HandAction:
    seq = await _next_seq(session, hand_id)
    action = HandAction(
        hand_id=hand_id,
        seq=seq,
        street=street,
        actor_account_id=actor_account_id,
        actor_seat_no=actor_seat_no,
        action_type=action_type,
        amount=amount,
        amount_to=amount_to,
        payload_json=json.dumps(payload) if payload else None,
        is_system_action=is_system,
    )
    session.add(action)
    return action


def _rotate_button(active_seat_nos: list[int], prev_button: int | None) -> int:
    """Return next button seat_no."""
    seats = sorted(active_seat_nos)
    if prev_button is None:
        return seats[0]
    try:
        idx = seats.index(prev_button)
    except ValueError:
        idx = -1
    return seats[(idx + 1) % len(seats)]


def _next_seat(seat_nos: list[int], after: int) -> int:
    seats = sorted(seat_nos)
    idx = next((i for i, s in enumerate(seats) if s > after), None)
    if idx is None:
        return seats[0]
    return seats[idx]


async def start_hand(session: AsyncSession, table_id: int) -> Hand | None:
    """Start a new hand for the given table. Returns None if can't start."""
    # Load table with seats
    result = await session.execute(
        select(Table).where(Table.id == table_id).options(selectinload(Table.seats))
    )
    table = result.scalar_one_or_none()
    if not table:
        return None

    # Eligible players: SEATED or LEAVING_AFTER_HAND, stack > 0
    eligible_seats = [
        s for s in table.seats
        if s.seat_status in (SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND) and s.stack > 0
    ]
    if len(eligible_seats) < 2:
        return None

    # Determine hand_no
    prev_hand_result = await session.execute(
        select(Hand)
        .where(Hand.table_id == table_id, Hand.status == HandStatus.FINISHED)
        .order_by(Hand.hand_no.desc())
    )
    prev_hand = prev_hand_result.scalars().first()
    hand_no = (prev_hand.hand_no + 1) if prev_hand else 1

    # Determine button from previous finished hand
    prev_button: int | None = None
    if prev_hand:
        prev_button = prev_hand.button_seat_no

    active_seat_nos = sorted(s.seat_no for s in eligible_seats)
    button_seat_no = _rotate_button(active_seat_nos, prev_button)

    # SB / BB
    heads_up = len(eligible_seats) == 2
    if heads_up:
        sb_seat_no = button_seat_no
        bb_seat_no = _next_seat(active_seat_nos, button_seat_no)
    else:
        sb_seat_no = _next_seat(active_seat_nos, button_seat_no)
        bb_seat_no = _next_seat(active_seat_nos, sb_seat_no)

    # Create Hand record
    hand = Hand(
        table_id=table_id,
        hand_no=hand_no,
        status=HandStatus.IN_PROGRESS,
        button_seat_no=button_seat_no,
        small_blind_seat_no=sb_seat_no,
        big_blind_seat_no=bb_seat_no,
        street="preflop",
        board_json="[]",
        current_bet=table.big_blind,
    )
    session.add(hand)
    await session.flush()

    # Create HandPlayer records
    seat_map = {s.seat_no: s for s in eligible_seats}
    players: dict[int, HandPlayer] = {}
    for seat in sorted(eligible_seats, key=lambda s: s.seat_no):
        hp = HandPlayer(
            hand_id=hand.id,
            account_id=seat.account_id,
            seat_no=seat.seat_no,
            hole_cards_json="[]",
            starting_stack=seat.stack,
            ending_stack=seat.stack,
            folded=False,
            all_in=False,
            round_contribution=0,
            hand_contribution=0,
        )
        session.add(hp)
        await session.flush()
        players[seat.seat_no] = hp

    # Post blinds
    sb_hp = players[sb_seat_no]
    sb_seat = seat_map[sb_seat_no]
    sb_amount = min(table.small_blind, sb_seat.stack)
    sb_seat.stack -= sb_amount
    sb_hp.round_contribution += sb_amount
    sb_hp.hand_contribution += sb_amount
    sb_hp.ending_stack = sb_seat.stack
    if sb_seat.stack == 0:
        sb_hp.all_in = True
    await _log_action(session, hand.id, "POST_SMALL_BLIND", "preflop",
                      sb_hp.account_id, sb_seat_no, amount=sb_amount)

    bb_hp = players[bb_seat_no]
    bb_seat = seat_map[bb_seat_no]
    bb_amount = min(table.big_blind, bb_seat.stack)
    bb_seat.stack -= bb_amount
    bb_hp.round_contribution += bb_amount
    bb_hp.hand_contribution += bb_amount
    bb_hp.ending_stack = bb_seat.stack
    if bb_seat.stack == 0:
        bb_hp.all_in = True
    await _log_action(session, hand.id, "POST_BIG_BLIND", "preflop",
                      bb_hp.account_id, bb_seat_no, amount=bb_amount)

    # Deal hole cards
    deck = Deck()
    deck.shuffle()
    for seat in sorted(eligible_seats, key=lambda s: s.seat_no):
        hole = deck.deal(2)
        players[seat.seat_no].hole_cards_json = json.dumps([str(c) for c in hole])

    hand.deck_json = deck.to_json()
    hand.deal_index = deck.deal_index
    await _log_action(session, hand.id, "DEAL_HOLE", "preflop")

    # Determine first actor (UTG for preflop)
    active = [s for s in active_seat_nos if not players[s].folded and not players[s].all_in]
    if heads_up:
        # button (SB) acts first preflop
        first_actor = button_seat_no
    else:
        # UTG = after BB
        first_actor = _next_seat(active, bb_seat_no)

    # If first_actor is all-in or folded, find next
    while active and players[first_actor].all_in:
        first_actor = _next_seat(active, first_actor)

    hand.action_seat_no = first_actor
    hand.action_deadline_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ACTION_TIMEOUT_SECONDS)

    await session.commit()
    return hand
