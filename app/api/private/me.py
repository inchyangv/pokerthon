from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.models.account import Account
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.table_public import MeResponse

router = APIRouter(prefix="/v1/private", tags=["private-me"])


@router.get("/me", response_model=MeResponse)
async def get_me(
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    result = await session.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one()

    # Find current table
    seat_r = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat = seat_r.scalar_one_or_none()
    current_table_no = None
    if seat:
        table_r = await session.execute(select(Table).where(Table.id == seat.table_id))
        table = table_r.scalar_one_or_none()
        if table:
            current_table_no = table.table_no

    return MeResponse(
        account_id=account.id,
        nickname=account.nickname,
        wallet_balance=account.wallet_balance,
        current_table_no=current_table_no,
    )
