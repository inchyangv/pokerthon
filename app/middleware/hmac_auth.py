"""
HMAC auth is implemented as a FastAPI Dependency (not middleware) so it works
with the test session factory override via dependency_overrides.
"""
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.signature import build_canonical_query_string, build_canonical_string, compute_signature
from app.database import get_session
from app.models.credential import ApiCredential, ApiNonce, CredentialStatus


async def require_hmac_auth(request: Request, session: AsyncSession = Depends(get_session)) -> int:
    """Validates HMAC signature and returns account_id."""
    api_key = request.headers.get("X-API-KEY", "")
    timestamp_str = request.headers.get("X-TIMESTAMP", "")
    nonce = request.headers.get("X-NONCE", "")
    signature = request.headers.get("X-SIGNATURE", "")

    if not all([api_key, timestamp_str, nonce, signature]):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Missing required authentication headers"},
        )

    try:
        ts = int(timestamp_str)
    except ValueError:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid timestamp"})

    now = int(time.time())
    if abs(now - ts) > 300:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Timestamp out of range"})

    body = await request.body()
    query_params = dict(request.query_params)
    qs = build_canonical_query_string(query_params)
    canonical = build_canonical_string(timestamp_str, nonce, request.method, request.url.path, qs, body)

    result = await session.execute(select(ApiCredential).where(ApiCredential.api_key == api_key))
    cred = result.scalar_one_or_none()

    if not cred:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid API key"})

    if cred.status != CredentialStatus.ACTIVE:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "API key is revoked"})

    expected_sig = compute_signature(cred.secret_hash, canonical)
    if signature != expected_sig:
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Invalid signature"})

    nonce_record = ApiNonce(api_key=api_key, nonce=nonce, timestamp=ts)
    session.add(nonce_record)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=401, detail={"code": "UNAUTHORIZED", "message": "Nonce already used"})

    cred.last_used_at = datetime.now(timezone.utc)
    await session.commit()

    return cred.account_id
