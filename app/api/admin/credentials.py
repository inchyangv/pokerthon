from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.schemas.credential import CredentialCreateResponse, CredentialListItem
from app.services.account_service import get_account
from app.services.credential_service import issue_credential, list_credentials, revoke_credential

router = APIRouter(prefix="/admin/accounts", tags=["admin-credentials"])


@router.post("/{account_id}/credentials", response_model=CredentialCreateResponse, status_code=201)
async def issue_credential_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    credential, raw_secret = await issue_credential(session, account_id)
    return CredentialCreateResponse(
        api_key=credential.api_key,
        secret_key=raw_secret,
        status=credential.status,
        created_at=credential.created_at,
    )


@router.post("/{account_id}/credentials/revoke", status_code=200)
async def revoke_credential_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    try:
        credential = await revoke_credential(session, account_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    return {"message": "Credential revoked", "api_key": credential.api_key}


@router.get("/{account_id}/credentials", response_model=list[CredentialListItem])
async def list_credentials_endpoint(account_id: int, session: AsyncSession = Depends(get_session)):
    account = await get_account(session, account_id)
    if not account:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Account not found"})
    return await list_credentials(session, account_id)
