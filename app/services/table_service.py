from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.models.table import SeatStatus, Table, TableSeat, TableStatus
from app.services.chip_service import transfer_from_table


async def _reload_with_seats(session: AsyncSession, table_id: int) -> Table:
    result = await session.execute(
        select(Table).where(Table.id == table_id).options(selectinload(Table.seats))
    )
    return result.scalar_one()


async def create_table(session: AsyncSession, table_no: int) -> Table:
    table = Table(
        table_no=table_no,
        status=TableStatus.OPEN,
        max_seats=9,
        small_blind=settings.SMALL_BLIND,
        big_blind=settings.BIG_BLIND,
        buy_in=settings.TABLE_BUYIN,
    )
    session.add(table)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ValueError(f"Table {table_no} already exists")

    for seat_no in range(1, 10):
        seat = TableSeat(table_id=table.id, seat_no=seat_no, seat_status=SeatStatus.EMPTY, stack=0)
        session.add(seat)

    await session.commit()
    return await _reload_with_seats(session, table.id)


async def get_table_by_no(session: AsyncSession, table_no: int, with_seats: bool = False) -> Table | None:
    q = select(Table).where(Table.table_no == table_no)
    if with_seats:
        q = q.options(selectinload(Table.seats))
    result = await session.execute(q)
    return result.scalar_one_or_none()


async def list_tables(session: AsyncSession) -> list[Table]:
    result = await session.execute(select(Table).order_by(Table.table_no))
    return list(result.scalars().all())


async def pause_table(session: AsyncSession, table_no: int) -> Table:
    table = await get_table_by_no(session, table_no)
    if not table:
        raise LookupError("Table not found")
    if table.status != TableStatus.OPEN:
        raise ValueError(f"Cannot pause table in status {table.status}")
    table.status = TableStatus.PAUSED
    await session.commit()
    return await _reload_with_seats(session, table.id)


async def resume_table(session: AsyncSession, table_no: int) -> Table:
    table = await get_table_by_no(session, table_no)
    if not table:
        raise LookupError("Table not found")
    if table.status != TableStatus.PAUSED:
        raise ValueError(f"Cannot resume table in status {table.status}")
    table.status = TableStatus.OPEN
    await session.commit()
    return await _reload_with_seats(session, table.id)


async def close_table(session: AsyncSession, table_no: int) -> Table:
    result = await session.execute(
        select(Table).where(Table.table_no == table_no).options(selectinload(Table.seats))
    )
    table = result.scalar_one_or_none()
    if not table:
        raise LookupError("Table not found")
    if table.status == TableStatus.CLOSED:
        raise ValueError("Table is already closed")

    for seat in table.seats:
        if seat.seat_status != SeatStatus.EMPTY:
            seat.seat_status = SeatStatus.EMPTY
            seat.account_id = None
            seat.stack = 0

    table.status = TableStatus.CLOSED
    await session.commit()
    return await _reload_with_seats(session, table.id)


async def merge_tables(session: AsyncSession, src_table_no: int, dst_table_no: int) -> dict:
    """Move all seated players from src table to dst table.

    Rules:
    - Both tables must exist and be OPEN or PAUSED
    - Neither table may have an active hand in progress
    - dst table must have enough empty seats for all src players
    """
    from app.models.hand import Hand, HandStatus

    src_r = await session.execute(
        select(Table).where(Table.table_no == src_table_no).options(selectinload(Table.seats))
    )
    src = src_r.scalar_one_or_none()
    if not src:
        raise LookupError(f"Source table {src_table_no} not found")

    dst_r = await session.execute(
        select(Table).where(Table.table_no == dst_table_no).options(selectinload(Table.seats))
    )
    dst = dst_r.scalar_one_or_none()
    if not dst:
        raise LookupError(f"Destination table {dst_table_no} not found")

    if src.id == dst.id:
        raise ValueError("Source and destination must be different tables")

    # Block if either table has a hand in progress
    for t in (src, dst):
        hand_r = await session.execute(
            select(Hand).where(Hand.table_id == t.id, Hand.status == HandStatus.IN_PROGRESS)
        )
        if hand_r.scalar_one_or_none():
            raise ValueError(f"Table {t.table_no} has an active hand — cannot merge")

    # Players to move
    moving = [s for s in src.seats if s.seat_status != SeatStatus.EMPTY]
    if not moving:
        raise ValueError(f"Source table {src_table_no} has no seated players")

    # Available seats at dst
    free_seats = sorted(
        [s for s in dst.seats if s.seat_status == SeatStatus.EMPTY],
        key=lambda s: s.seat_no,
    )
    if len(free_seats) < len(moving):
        raise ValueError(
            f"Destination table {dst_table_no} only has {len(free_seats)} free seats "
            f"but {len(moving)} players need to move"
        )

    # Move players
    moved = []
    for player_seat, target_seat in zip(moving, free_seats):
        target_seat.account_id = player_seat.account_id
        target_seat.seat_status = player_seat.seat_status
        target_seat.stack = player_seat.stack
        target_seat.joined_at = player_seat.joined_at

        player_seat.account_id = None
        player_seat.seat_status = SeatStatus.EMPTY
        player_seat.stack = 0
        player_seat.joined_at = None

        moved.append({"from_seat": player_seat.seat_no, "to_seat": target_seat.seat_no})

    await session.commit()
    return {"moved": moved, "src_table_no": src_table_no, "dst_table_no": dst_table_no}


async def delete_table(session: AsyncSession, table_no: int) -> None:
    """Hard-delete a table and all associated records.

    Deletion order (FK dependencies):
    1. HandAction  → FK hands.id
    2. HandPlayer  → FK hands.id
    3. HandResult  → FK hands.id
    4. Hand        → FK tables.id
    5. TableSnapshot → FK tables.id
    6. TableSeat   → FK tables.id
    7. Table
    """
    from app.models.hand import Hand, HandAction, HandPlayer, HandResult, TableSnapshot

    result = await session.execute(select(Table).where(Table.table_no == table_no))
    table = result.scalar_one_or_none()
    if not table:
        raise LookupError(f"Table {table_no} not found")

    # Collect hand IDs for this table
    hand_ids_r = await session.execute(
        select(Hand.id).where(Hand.table_id == table.id)
    )
    hand_ids = [row[0] for row in hand_ids_r.all()]

    if hand_ids:
        await session.execute(delete(HandAction).where(HandAction.hand_id.in_(hand_ids)))
        await session.execute(delete(HandPlayer).where(HandPlayer.hand_id.in_(hand_ids)))
        await session.execute(delete(HandResult).where(HandResult.hand_id.in_(hand_ids)))
        await session.execute(delete(Hand).where(Hand.table_id == table.id))

    await session.execute(delete(TableSnapshot).where(TableSnapshot.table_id == table.id))
    await session.execute(delete(TableSeat).where(TableSeat.table_id == table.id))
    await session.delete(table)
    await session.commit()
