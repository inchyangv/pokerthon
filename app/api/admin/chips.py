from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.schemas.account import AccountResponse
from app.schemas.chip import ChipDeductRequest, ChipGrantRequest, LedgerEntry
from app.services.account_service import get_account
from app.services.chip_service import deduct, get_ledger, grant

router = APIRouter(prefix="/admin/accounts", tags=["admin-chips"])


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


@router.get("/{account_id}/ledger", response_model=list[LedgerEntry])
async def get_ledger_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    return await get_ledger(session, account_id)
