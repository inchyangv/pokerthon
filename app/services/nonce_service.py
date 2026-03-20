from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credential import ApiNonce


async def check_and_store_nonce(session: AsyncSession, api_key: str, nonce: str, timestamp: int) -> bool:
    """Returns True if nonce is fresh (stored successfully). False if duplicate."""
    record = ApiNonce(api_key=api_key, nonce=nonce, timestamp=timestamp)
    session.add(record)
    try:
        await session.flush()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def cleanup_expired_nonces(session: AsyncSession, cutoff_timestamp: int) -> int:
    from sqlalchemy import delete
    result = await session.execute(
        delete(ApiNonce).where(ApiNonce.timestamp < cutoff_timestamp)
    )
    await session.commit()
    return result.rowcount
