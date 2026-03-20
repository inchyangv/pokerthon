from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.account import AccountCreate, AccountResponse
from app.services.account_service import create_account, delete_account, get_account, list_accounts, rename_account

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


class RenameBody(BaseModel):
    nickname: str


@router.patch("/{account_id}/nickname", response_model=AccountResponse)
async def rename_account_endpoint(
    account_id: int,
    body: RenameBody,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await rename_account(session, account_id, body.nickname.strip())
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValueError as e:
        raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": str(e)})


@router.delete("/{account_id}", status_code=204)
async def delete_account_endpoint(
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    try:
        await delete_account(session, account_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
