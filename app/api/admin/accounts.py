from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.account import AccountCreate, AccountResponse
from app.services.account_service import create_account, get_account, list_accounts

router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])


@router.post("", response_model=AccountResponse, status_code=201)
async def create_account_endpoint(body: AccountCreate, session: AsyncSession = Depends(get_session)):
    try:
        account = await create_account(session, body.nickname)
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})
    return account


@router.get("", response_model=list[AccountResponse])
async def list_accounts_endpoint(session: AsyncSession = Depends(get_session)):
    return await list_accounts(session)


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    return account
