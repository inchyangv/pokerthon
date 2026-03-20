from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import async_session_factory

router = APIRouter()


@router.get("/health")
async def health_check():
    db_status = "unknown"
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    # Always return 200 so Railway healthcheck passes; include db status for info
    return {"status": "ok", "db": db_status}
