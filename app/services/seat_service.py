from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat, TableStatus


async def get_current_seat(session: AsyncSession, account_id: int) -> TableSeat | None:
    result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    return result.scalar_one_or_none()


async def sit(session: AsyncSession, account_id: int, table_no: int, seat_no: int | None) -> TableSeat:
    from sqlalchemy import select
    # Load table with seats
    result = await session.execute(
        select(Table).where(Table.table_no == table_no).options(selectinload(Table.seats))
    )
    table = result.scalar_one_or_none()
    if not table:
        raise LookupError("Table not found")
    if table.status != TableStatus.OPEN:
        raise ValueError("INVALID_ACTION: Table is not open")

    # Check already seated anywhere
    existing = await get_current_seat(session, account_id)
    if existing:
        if existing.table_id == table.id:
            raise ValueError("CONFLICT: Already seated at this table")
        raise ValueError(f"CONFLICT: Already seated at table {table.table_no if existing.table_id else '?'}")

    # Validate seat_no range
    if seat_no is not None and not (1 <= seat_no <= 9):
        raise ValueError("INVALID_ACTION: seat_no must be between 1 and 9")

    # Find target seat
    seats_by_no = {s.seat_no: s for s in table.seats}
    if seat_no is not None:
        target = seats_by_no.get(seat_no)
        if not target or target.seat_status != SeatStatus.EMPTY:
            raise ValueError("SEAT_TAKEN: Requested seat is not available")
    else:
        target = next(
            (s for s in sorted(table.seats, key=lambda x: x.seat_no) if s.seat_status == SeatStatus.EMPTY),
            None,
        )
        if not target:
            raise ValueError("TABLE_FULL: No empty seats available")

    # Require minimum wallet balance to deploy a stack (chips are account assets; no deduction)
    from app.models.account import Account
    acc_result = await session.execute(select(Account).where(Account.id == account_id))
    account = acc_result.scalar_one()
    if account.wallet_balance < table.buy_in:
        raise ValueError("INSUFFICIENT_BALANCE: Not enough chips")

    # Update seat (wallet_balance is NOT deducted; wallet always reflects total chip count)
    target.account_id = account_id
    target.seat_status = SeatStatus.SEATED
    target.stack = table.buy_in
    target.joined_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(target)
    return target


async def stand(session: AsyncSession, account_id: int, table_no: int) -> dict:
    result = await session.execute(
        select(Table).where(Table.table_no == table_no)
    )
    table = result.scalar_one_or_none()
    if not table:
        raise LookupError("Table not found")

    seat_result = await session.execute(
        select(TableSeat).where(
            TableSeat.table_id == table.id,
            TableSeat.account_id == account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat = seat_result.scalar_one_or_none()
    if not seat:
        raise LookupError("Not seated at this table")

    # Check if active hand in progress and player is in it
    active_hand = await _get_active_hand_for_player(session, table.id, account_id)

    if active_hand is not None:
        # Mark as leaving after hand
        seat.seat_status = SeatStatus.LEAVING_AFTER_HAND
        await session.commit()
        return {"immediate": False, "message": "Will leave after current hand ends"}
    else:
        # Immediate leave — wallet_balance is unaffected (no prior deduction)
        seat.seat_status = SeatStatus.EMPTY
        seat.account_id = None
        seat.stack = 0
        await session.commit()
        return {"immediate": True, "message": "Left table immediately"}


async def _get_active_hand_for_player(session: AsyncSession, table_id: int, account_id: int) -> Hand | None:
    """Returns the active hand if this player is currently in it."""
    result = await session.execute(
        select(Hand).where(
            Hand.table_id == table_id,
            Hand.status == HandStatus.IN_PROGRESS,
        )
    )
    hand = result.scalar_one_or_none()
    if not hand:
        return None

    player_result = await session.execute(
        select(HandPlayer).where(
            HandPlayer.hand_id == hand.id,
            HandPlayer.account_id == account_id,
        )
    )
    player = player_result.scalar_one_or_none()
    return hand if player else None
