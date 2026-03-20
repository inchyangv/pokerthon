from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.middleware.hmac_auth import require_hmac_auth
from app.models.account import Account
from app.models.chip import ChipLedger, LedgerReasonType
from app.models.table import SeatStatus, Table, TableSeat
from app.schemas.table_public import MeResponse

router = APIRouter(prefix="/v1/private", tags=["private-me"])

# Test-period refill expires at end of 2026-03-31 UTC
_TEST_PERIOD_END = datetime(2026, 3, 31, 23, 59, 59, tzinfo=timezone.utc)


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


@router.post("/test/refill", summary="[TEST PERIOD ONLY] Refill wallet to buy-in amount")
async def test_refill(
    session: AsyncSession = Depends(get_session),
    account_id: int = Depends(require_hmac_auth),
):
    """Refill wallet_balance to TABLE_BUYIN (40) if currently below it.

    Available only during the test period (until 2026-03-31 23:59:59 UTC).
    Returns 410 Gone after expiry.
    """
    if datetime.now(timezone.utc) > _TEST_PERIOD_END:
        raise HTTPException(
            status_code=410,
            detail={"code": "TEST_PERIOD_ENDED", "message": "Test period has ended. Refill is no longer available."},
        )

    result = await session.execute(select(Account).where(Account.id == account_id).with_for_update())
    account = result.scalar_one()

    top_up = max(0, settings.TABLE_BUYIN - account.wallet_balance)
    if top_up > 0:
        account.wallet_balance += top_up
        session.add(ChipLedger(
            account_id=account_id,
            delta=top_up,
            balance_after=account.wallet_balance,
            reason_type=LedgerReasonType.ADMIN_GRANT,
            reason_text="test period refill",
        ))
        await session.commit()
        await session.refresh(account)

    return {
        "wallet_balance": account.wallet_balance,
        "refilled": top_up,
        "test_period_ends": _TEST_PERIOD_END.isoformat(),
    }
