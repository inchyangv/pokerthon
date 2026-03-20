from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.chip import ChipLedger, LedgerReasonType


async def _record_ledger(
    session: AsyncSession,
    account_id: int,
    delta: int,
    balance_after: int,
    reason_type: LedgerReasonType,
    reason_text: str = "",
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> ChipLedger:
    entry = ChipLedger(
        account_id=account_id,
        delta=delta,
        balance_after=balance_after,
        reason_type=reason_type,
        reason_text=reason_text or None,
        ref_type=ref_type,
        ref_id=ref_id,
    )
    session.add(entry)
    return entry


async def grant(
    session: AsyncSession,
    account_id: int,
    amount: int,
    reason_text: str = "",
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> Account:
    result = await session.execute(select(Account).where(Account.id == account_id).with_for_update())
    account = result.scalar_one()
    account.wallet_balance += amount
    await _record_ledger(
        session, account_id, delta=amount, balance_after=account.wallet_balance,
        reason_type=LedgerReasonType.ADMIN_GRANT, reason_text=reason_text,
        ref_type=ref_type, ref_id=ref_id,
    )
    await session.commit()
    await session.refresh(account)
    return account


async def deduct(
    session: AsyncSession,
    account_id: int,
    amount: int,
    reason_text: str = "",
    reason_type: LedgerReasonType = LedgerReasonType.ADMIN_DEDUCT,
    ref_type: str | None = None,
    ref_id: int | None = None,
) -> Account:
    result = await session.execute(select(Account).where(Account.id == account_id).with_for_update())
    account = result.scalar_one()
    if account.wallet_balance < amount:
        raise ValueError("INSUFFICIENT_BALANCE")
    account.wallet_balance -= amount
    await _record_ledger(
        session, account_id, delta=-amount, balance_after=account.wallet_balance,
        reason_type=reason_type, reason_text=reason_text,
        ref_type=ref_type, ref_id=ref_id,
    )
    await session.commit()
    await session.refresh(account)
    return account


async def transfer_to_table(
    session: AsyncSession,
    account_id: int,
    amount: int,
    table_id: int,
) -> Account:
    """Deduct buy_in from wallet for table seating."""
    return await deduct(
        session, account_id, amount,
        reason_text="table buy-in",
        reason_type=LedgerReasonType.TABLE_BUYIN,
        ref_type="table",
        ref_id=table_id,
    )


async def transfer_from_table(
    session: AsyncSession,
    account_id: int,
    amount: int,
    table_id: int,
) -> Account:
    """Return stack from table back to wallet."""
    result = await session.execute(select(Account).where(Account.id == account_id).with_for_update())
    account = result.scalar_one()
    account.wallet_balance += amount
    await _record_ledger(
        session, account_id, delta=amount, balance_after=account.wallet_balance,
        reason_type=LedgerReasonType.TABLE_CASHOUT,
        reason_text="table cashout",
        ref_type="table",
        ref_id=table_id,
    )
    await session.commit()
    await session.refresh(account)
    return account


async def get_ledger(session: AsyncSession, account_id: int) -> list[ChipLedger]:
    result = await session.execute(
        select(ChipLedger)
        .where(ChipLedger.account_id == account_id)
        .order_by(ChipLedger.id.desc())
    )
    return list(result.scalars().all())
