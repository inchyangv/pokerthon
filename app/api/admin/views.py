"""Admin web UI — HTML views for accounts, credentials, and chips."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.account import Account
from app.models.chip import ChipLedger
from app.models.credential import ApiCredential, CredentialStatus
from app.models.table import SeatStatus, Table, TableSeat
from app.services import chip_service, credential_service

router = APIRouter(prefix="/admin", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")

_SESSION_COOKIE = "admin_session"
_SESSION_VALUE = "authenticated"


def _is_authenticated(request: Request) -> bool:
    return request.cookies.get(_SESSION_COOKIE) == _SESSION_VALUE


def _redirect_login(next_url: str = "/admin/") -> RedirectResponse:
    return RedirectResponse(url=f"/admin/login?next={next_url}", status_code=302)


def _flash(request: Request, flash: dict | None = None):
    return {"request": request, "flash": flash}


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "admin/login.html", { "error": None})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if password == settings.ADMIN_PASSWORD:
        response = RedirectResponse(url="/admin/", status_code=302)
        response.set_cookie(_SESSION_COOKIE, _SESSION_VALUE, httponly=True, samesite="lax")
        return response
    return templates.TemplateResponse(request, "admin/login.html", {"error": "비밀번호가 틀렸습니다."})


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(_SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    if not _is_authenticated(request):
        return _redirect_login()

    acc_count = (await session.execute(select(func.count(Account.id)))).scalar_one()
    table_count = (await session.execute(select(func.count(Table.id)))).scalar_one()
    total_chips = (await session.execute(
        select(func.coalesce(func.sum(Account.wallet_balance), 0))
    )).scalar_one()

    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "request": request,
        "flash": None,
        "account_count": acc_count,
        "table_count": table_count,
        "total_chips": total_chips,
    })


# ---------------------------------------------------------------------------
# Account list + create
# ---------------------------------------------------------------------------

@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, session: AsyncSession = Depends(get_session)):
    if not _is_authenticated(request):
        return _redirect_login("/admin/accounts")

    result = await session.execute(select(Account).order_by(Account.id.desc()))
    accounts = result.scalars().all()
    return templates.TemplateResponse(request, "admin/accounts.html", {
        "request": request, "flash": None, "accounts": accounts,
    })


@router.post("/accounts/create", response_class=HTMLResponse)
async def create_account(
    request: Request,
    nickname: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    existing = (await session.execute(
        select(Account).where(Account.nickname == nickname)
    )).scalar_one_or_none()

    if existing:
        result = await session.execute(select(Account).order_by(Account.id.desc()))
        return templates.TemplateResponse(request, "admin/accounts.html", {
            "request": request,
            "flash": {"type": "error", "message": f"닉네임 '{nickname}'은 이미 사용 중입니다."},
            "accounts": result.scalars().all(),
        })

    from app.models.account import AccountStatus
    acc = Account(nickname=nickname, status=AccountStatus.ACTIVE, wallet_balance=0)
    session.add(acc)
    await session.commit()
    return RedirectResponse(url=f"/admin/accounts/{acc.id}", status_code=302)


# ---------------------------------------------------------------------------
# Account detail
# ---------------------------------------------------------------------------

async def _get_account_credential(session: AsyncSession, account_id: int):
    result = await session.execute(
        select(ApiCredential)
        .where(ApiCredential.account_id == account_id)
        .order_by(ApiCredential.id.desc())
    )
    return result.scalars().first()


@router.get("/accounts/{account_id}", response_class=HTMLResponse)
async def account_detail(
    request: Request,
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    account = await session.get(Account, account_id)
    if not account:
        return HTMLResponse("Not found", status_code=404)

    credential = await _get_account_credential(session, account_id)
    ledger_result = await session.execute(
        select(ChipLedger)
        .where(ChipLedger.account_id == account_id)
        .order_by(ChipLedger.id.desc())
        .limit(50)
    )
    ledger = list(ledger_result.scalars().all())

    # Current table
    seat_result = await session.execute(
        select(TableSeat).where(
            TableSeat.account_id == account_id,
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND]),
        )
    )
    seat = seat_result.scalar_one_or_none()
    current_table_no = None
    if seat:
        table = await session.get(Table, seat.table_id)
        if table:
            current_table_no = table.table_no

    # Pop flash from session (stored in cookie via query param trick)
    flash = None
    new_secret = request.query_params.get("new_secret")
    if new_secret:
        flash = {"type": "success", "message": "새 API 키가 발급되었습니다."}

    error = request.query_params.get("error")
    if error:
        flash = {"type": "error", "message": error}

    return templates.TemplateResponse(request, "admin/account_detail.html", {
        "request": request,
        "flash": flash,
        "account": account,
        "credential": credential,
        "ledger": ledger,
        "current_table_no": current_table_no,
        "new_secret": new_secret,
    })


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

@router.post("/accounts/{account_id}/credentials/issue")
async def issue_credential(
    request: Request,
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    _, raw_secret = await credential_service.issue_credential(session, account_id)
    return RedirectResponse(
        url=f"/admin/accounts/{account_id}?new_secret={raw_secret}",
        status_code=302,
    )


@router.post("/accounts/{account_id}/credentials/revoke")
async def revoke_credential(
    request: Request,
    account_id: int,
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    cred = await _get_account_credential(session, account_id)
    if cred and cred.status == CredentialStatus.ACTIVE:
        await credential_service.revoke_credential(session, account_id)

    return RedirectResponse(url=f"/admin/accounts/{account_id}", status_code=302)


# ---------------------------------------------------------------------------
# Chips
# ---------------------------------------------------------------------------

@router.post("/accounts/{account_id}/grant")
async def grant_chips(
    request: Request,
    account_id: int,
    amount: int = Form(...),
    reason: str = Form(default="admin_grant"),
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    try:
        await chip_service.grant(session, account_id, amount, reason_text=reason)
    except Exception as e:
        return RedirectResponse(url=f"/admin/accounts/{account_id}?error={e}", status_code=302)

    return RedirectResponse(url=f"/admin/accounts/{account_id}", status_code=302)


@router.post("/accounts/{account_id}/deduct")
async def deduct_chips(
    request: Request,
    account_id: int,
    amount: int = Form(...),
    reason: str = Form(default="admin_deduct"),
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    try:
        await chip_service.deduct(session, account_id, amount, reason_text=reason)
    except Exception as e:
        return RedirectResponse(url=f"/admin/accounts/{account_id}?error={e}", status_code=302)

    return RedirectResponse(url=f"/admin/accounts/{account_id}", status_code=302)
