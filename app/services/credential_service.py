from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import generate_api_key, generate_secret_key, hash_secret, verify_secret
from app.models.credential import ApiCredential, CredentialStatus


async def issue_credential(session: AsyncSession, account_id: int) -> tuple[ApiCredential, str]:
    """Issues a new credential. Revokes any existing active credential. Returns (credential, raw_secret)."""
    # Revoke existing active credential
    result = await session.execute(
        select(ApiCredential)
        .where(ApiCredential.account_id == account_id, ApiCredential.status == CredentialStatus.ACTIVE)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.status = CredentialStatus.REVOKED
        existing.revoked_at = datetime.now(timezone.utc)

    raw_secret = generate_secret_key()
    credential = ApiCredential(
        account_id=account_id,
        api_key=generate_api_key(),
        secret_hash=hash_secret(raw_secret),
        status=CredentialStatus.ACTIVE,
    )
    session.add(credential)
    await session.commit()
    await session.refresh(credential)
    return credential, raw_secret


async def revoke_credential(session: AsyncSession, account_id: int) -> ApiCredential:
    """Revokes the active credential. Raises ValueError if none active."""
    result = await session.execute(
        select(ApiCredential)
        .where(ApiCredential.account_id == account_id, ApiCredential.status == CredentialStatus.ACTIVE)
    )
    credential = result.scalar_one_or_none()
    if not credential:
        raise ValueError("No active credential found")
    credential.status = CredentialStatus.REVOKED
    credential.revoked_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(credential)
    return credential


async def list_credentials(session: AsyncSession, account_id: int) -> list[ApiCredential]:
    result = await session.execute(
        select(ApiCredential).where(ApiCredential.account_id == account_id).order_by(ApiCredential.created_at.desc())
    )
    return list(result.scalars().all())


async def get_active_credential_by_api_key(session: AsyncSession, api_key: str) -> ApiCredential | None:
    result = await session.execute(
        select(ApiCredential)
        .where(ApiCredential.api_key == api_key, ApiCredential.status == CredentialStatus.ACTIVE)
    )
    return result.scalar_one_or_none()


async def verify_credential(session: AsyncSession, api_key: str, raw_secret: str) -> ApiCredential | None:
    result = await session.execute(
        select(ApiCredential).where(ApiCredential.api_key == api_key)
    )
    cred = result.scalar_one_or_none()
    if cred and cred.status == CredentialStatus.ACTIVE and verify_secret(raw_secret, cred.secret_hash):
        return cred
    return None
