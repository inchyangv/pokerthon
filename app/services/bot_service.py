"""Bot business logic — create, list, seat, unseat, deactivate."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bots import BotType
from app.config import settings
from app.models.account import Account
from app.models.bot import BotProfile
from app.models.table import SeatStatus, Table, TableSeat
from app.services.chip_service import grant
from app.services.seat_service import sit, stand


async def create_bot(
    session: AsyncSession, bot_type: str, display_name: str
) -> dict:
    """Create a bot account + profile and grant initial chips."""
    if bot_type not in (t.value for t in BotType):
        raise ValueError(f"Invalid bot_type: {bot_type}")

    # Check duplicate display_name
    existing = await session.execute(
        select(Account).where(Account.nickname == display_name)
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"CONFLICT: nickname '{display_name}' already exists")

    # Create account
    account = Account(nickname=display_name, is_bot=True)
    session.add(account)
    await session.flush()

    # Create bot profile
    bot = BotProfile(
        account_id=account.id,
        bot_type=bot_type,
        display_name=display_name,
        is_active=True,
    )
    session.add(bot)
    await session.flush()

    # Grant initial chips
    account.wallet_balance += settings.BOT_INITIAL_CHIPS
    from app.models.chip import ChipLedger, LedgerReasonType
    ledger = ChipLedger(
        account_id=account.id,
        delta=settings.BOT_INITIAL_CHIPS,
        balance_after=account.wallet_balance,
        reason_type=LedgerReasonType.ADMIN_GRANT,
        reason_text="Bot initial chips",
    )
    session.add(ledger)
    await session.commit()

    return {
        "bot_id": bot.id,
        "account_id": account.id,
        "bot_type": bot_type,
        "display_name": display_name,
        "chips": account.wallet_balance,
    }


async def list_bots(session: AsyncSession, is_active: bool | None = None) -> list[dict]:
    """List all bots with current seating info."""
    query = select(BotProfile)
    if is_active is not None:
        query = query.where(BotProfile.is_active == is_active)
    result = await session.execute(query)
    bots = list(result.scalars().all())

    items = []
    for bot in bots:
        acc_result = await session.execute(
            select(Account).where(Account.id == bot.account_id)
        )
        account = acc_result.scalar_one()

        # Find current seat
        seat_result = await session.execute(
            select(TableSeat).where(
                TableSeat.account_id == bot.account_id,
                TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
            )
        )
        seat = seat_result.scalar_one_or_none()

        table_no = None
        if seat:
            table_result = await session.execute(
                select(Table).where(Table.id == seat.table_id)
            )
            table = table_result.scalar_one()
            table_no = table.table_no

        items.append({
            "bot_id": bot.id,
            "account_id": account.id,
            "bot_type": bot.bot_type,
            "display_name": bot.display_name,
            "is_active": bot.is_active,
            "wallet_balance": account.wallet_balance,
            "table_no": table_no,
            "seat_no": seat.seat_no if seat else None,
            "stack": seat.stack if seat else None,
        })
    return items


async def seat_bot(
    session: AsyncSession, bot_id: int, table_no: int, seat_no: int | None = None
) -> TableSeat:
    bot_result = await session.execute(select(BotProfile).where(BotProfile.id == bot_id))
    bot = bot_result.scalar_one_or_none()
    if not bot or not bot.is_active:
        raise LookupError("Bot not found or inactive")

    # Check already seated
    existing_result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == bot.account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    if existing_result.scalar_one_or_none():
        raise ValueError("CONFLICT: Bot already seated")

    return await sit(session, bot.account_id, table_no, seat_no)


async def unseat_bot(session: AsyncSession, bot_id: int) -> dict:
    bot_result = await session.execute(select(BotProfile).where(BotProfile.id == bot_id))
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise LookupError("Bot not found")

    # Find current seat
    seat_result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == bot.account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat = seat_result.scalar_one_or_none()
    if not seat:
        raise LookupError("Bot not currently seated")

    table_result = await session.execute(select(Table).where(Table.id == seat.table_id))
    table = table_result.scalar_one()
    return await stand(session, bot.account_id, table.table_no)


async def deactivate_bot(session: AsyncSession, bot_id: int) -> None:
    bot_result = await session.execute(select(BotProfile).where(BotProfile.id == bot_id))
    bot = bot_result.scalar_one_or_none()
    if not bot:
        raise LookupError("Bot not found")

    # Unseat if seated (best-effort)
    try:
        await unseat_bot(session, bot_id)
    except LookupError:
        pass  # Not seated, that's fine

    bot.is_active = False
    await session.commit()
