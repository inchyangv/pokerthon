from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.schemas.seat import SitRequest
from app.services.seat_service import sit, stand

router = APIRouter(prefix="/v1/private/tables", tags=["private-tables"])


@router.post("/{table_no}/sit")
async def sit_endpoint(
    table_no: int,
    body: SitRequest = SitRequest(),
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    try:
        seat = await sit(session, account_id, table_no, body.seat_no)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    except ValueError as e:
        msg = str(e)
        if msg.startswith("CONFLICT"):
            raise HTTPException(status_code=409, detail={"code": "CONFLICT", "message": msg})
        if msg.startswith("SEAT_TAKEN"):
            raise HTTPException(status_code=409, detail={"code": "SEAT_TAKEN", "message": msg})
        if msg.startswith("TABLE_FULL"):
            raise HTTPException(status_code=422, detail={"code": "TABLE_FULL", "message": msg})
        if msg.startswith("INSUFFICIENT_BALANCE"):
            raise HTTPException(status_code=422, detail={"code": "INSUFFICIENT_BALANCE", "message": msg})
        raise HTTPException(status_code=422, detail={"code": "INVALID_ACTION", "message": msg})
    return {
        "table_no": table_no,
        "seat_no": seat.seat_no,
        "stack": seat.stack,
        "seat_status": seat.seat_status,
    }


@router.post("/{table_no}/stand")
async def stand_endpoint(
    table_no: int,
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    try:
        result = await stand(session, account_id, table_no)
    except LookupError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
    return result
