from sqlalchemy import select
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
