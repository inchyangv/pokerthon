from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.schemas.account import AccountResponse
from app.schemas.chip import ChipDeductRequest, ChipGrantRequest, LedgerEntry
from app.services.account_service import get_account
from app.services.chip_service import deduct, get_ledger, grant

router = APIRouter(prefix="/admin/accounts", tags=["admin-chips"])


class SetBalanceBody(BaseModel):
    amount: int


@router.post("/{account_id}/grant", response_model=AccountResponse)
async def grant_chips(account_id: int, body: ChipGrantRequest, session: AsyncSession = Depends(get_session)):
    if settings.TOURNAMENT_MODE:
        raise HTTPException(
            status_code=403,
            detail={"code": "TOURNAMENT_MODE", "message": "Chip grants are disabled during tournament mode"},
        )
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    account = await grant(session, account_id, body.amount, reason_text=body.reason)
    return account


@router.post("/{account_id}/deduct", response_model=AccountResponse)
async def deduct_chips(account_id: int, body: ChipDeductRequest, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    try:
        account = await deduct(session, account_id, body.amount, reason_text=body.reason)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"code": "INSUFFICIENT_BALANCE", "message": "Insufficient wallet balance"},
        )
    return account


@router.post("/{account_id}/set-balance", response_model=AccountResponse)
async def set_balance(account_id: int, body: SetBalanceBody, session: AsyncSession = Depends(get_session)):
    """Admin: hard-set wallet balance, bypassing TOURNAMENT_MODE. Use only for pre-tournament setup."""
    if body.amount < 0:
        raise HTTPException(status_code=422, detail={"code": "INVALID", "message": "amount must be >= 0"})
    from sqlalchemy import select
    from app.models.account import Account
    from app.models.chip import ChipLedger, LedgerReasonType
    result = await session.execute(select(Account).where(Account.id == account_id).with_for_update())
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    delta = body.amount - account.wallet_balance
    account.wallet_balance = body.amount
    entry = ChipLedger(
        account_id=account_id,
        delta=delta,
        balance_after=body.amount,
        reason_type=LedgerReasonType.ADMIN_GRANT if delta >= 0 else LedgerReasonType.ADMIN_DEDUCT,
        reason_text="admin_set_balance",
    )
    session.add(entry)
    await session.commit()
    await session.refresh(account)
    return account


@router.get("/{account_id}/ledger", response_model=list[LedgerEntry])
async def get_ledger_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    return await get_ledger(session, account_id)
