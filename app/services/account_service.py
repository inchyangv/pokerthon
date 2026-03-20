from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account, AccountStatus


async def create_account(session: AsyncSession, nickname: str) -> Account:
    account = Account(nickname=nickname, status=AccountStatus.ACTIVE, wallet_balance=0)
    session.add(account)
    try:
        await session.commit()
        await session.refresh(account)
    except IntegrityError:
        await session.rollback()
        raise ValueError(f"Nickname '{nickname}' already exists")
    return account


async def get_account(session: AsyncSession, account_id: int) -> Account | None:
    result = await session.execute(select(Account).where(Account.id == account_id))
    return result.scalar_one_or_none()


async def list_accounts(session: AsyncSession) -> list[Account]:
    result = await session.execute(select(Account).order_by(Account.id))
    return list(result.scalars().all())


async def rename_account(session: AsyncSession, account_id: int, new_nickname: str) -> Account:
    account = await session.get(Account, account_id)
    if not account:
        raise LookupError(f"Account {account_id} not found")
    existing = (await session.execute(
        select(Account).where(Account.nickname == new_nickname, Account.id != account_id)
    )).scalar_one_or_none()
    if existing:
        raise ValueError(f"Nickname '{new_nickname}' is already taken")
    account.nickname = new_nickname
    await session.commit()
    await session.refresh(account)
    return account


async def delete_account(session: AsyncSession, account_id: int) -> None:
    """Hard-delete an account and all associated records.

    Deletion order (FK dependencies):
    1. Clear TableSeat (set EMPTY, account_id=None) — preserve seat row
    2. Delete HandPlayer rows (FK NOT NULL, must go before Account)
    3. Delete HandAction rows referencing this account
    4. Delete ApiCredential, ChipLedger, BotProfile
    5. Delete Account
    """
    from app.models.bot import BotProfile
    from app.models.chip import ChipLedger
    from app.models.credential import ApiCredential
    from app.models.hand import HandAction, HandPlayer
    from app.models.table import SeatStatus, TableSeat

    account = await session.get(Account, account_id)
    if not account:
        raise LookupError(f"Account {account_id} not found")

    # 1. Vacate any seats
    seats_r = await session.execute(
        select(TableSeat).where(TableSeat.account_id == account_id)
    )
    for seat in seats_r.scalars().all():
        seat.account_id = None
        seat.seat_status = SeatStatus.EMPTY
        seat.stack = 0

    # 2. Delete HandPlayer rows
    await session.execute(delete(HandPlayer).where(HandPlayer.account_id == account_id))

    # 3. Nullify HandAction actor references (column is nullable)
    actions_r = await session.execute(
        select(HandAction).where(HandAction.actor_account_id == account_id)
    )
    for action in actions_r.scalars().all():
        action.actor_account_id = None

    # 4. Delete credentials, ledger, bot profile
    await session.execute(delete(ApiCredential).where(ApiCredential.account_id == account_id))
    await session.execute(delete(ChipLedger).where(ChipLedger.account_id == account_id))
    await session.execute(delete(BotProfile).where(BotProfile.account_id == account_id))

    # 5. Delete account
    await session.delete(account)
    await session.commit()
