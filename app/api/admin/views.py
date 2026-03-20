"""Admin web UI — HTML views for accounts, credentials, chips, tables, and games."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models.account import Account
from app.models.bot import BotProfile
from app.models.chip import ChipLedger
from app.models.credential import ApiCredential, CredentialStatus
from app.models.hand import Hand, HandPlayer, HandStatus
from app.models.table import SeatStatus, Table, TableSeat
from app.services import chip_service, credential_service
from app.services.history_service import get_hand_actions

router = APIRouter(prefix="/admin", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")

_SESSION_COOKIE = "admin_session"
# Server-side session store: token -> True
_active_sessions: set[str] = set()


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(_SESSION_COOKIE)
    return token is not None and token in _active_sessions


def _is_api_request(request: Request) -> bool:
    """True when the request comes from an API client (Bearer token, not browser cookie)."""
    return bool(request.headers.get("Authorization"))


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
    if secrets.compare_digest(password, settings.ADMIN_PASSWORD):
        token = secrets.token_urlsafe(32)
        _active_sessions.add(token)
        is_https = request.url.scheme == "https"
        response = RedirectResponse(url="/admin/", status_code=302)
        response.set_cookie(_SESSION_COOKIE, token, httponly=True, samesite="strict" if is_https else "lax", secure=is_https)
        return response
    return templates.TemplateResponse(request, "admin/login.html", {"error": "비밀번호가 틀렸습니다."})


@router.get("/logout")
async def logout(request: Request):
    token = request.cookies.get(_SESSION_COOKIE)
    if token:
        _active_sessions.discard(token)
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
    active_bot_count = (await session.execute(
        select(func.count(BotProfile.id)).where(BotProfile.is_active == True)  # noqa: E712
    )).scalar_one()
    seated_bot_count = (await session.execute(
        select(func.count(TableSeat.id)).where(
            TableSeat.seat_status.in_([SeatStatus.SEATED, SeatStatus.LEAVING_AFTER_HAND])
        ).join(Account, Account.id == TableSeat.account_id).where(Account.is_bot == True)  # noqa: E712
    )).scalar_one()

    return templates.TemplateResponse(request, "admin/dashboard.html", {
        "request": request,
        "flash": None,
        "account_count": acc_count,
        "table_count": table_count,
        "total_chips": total_chips,
        "active_bot_count": active_bot_count,
        "seated_bot_count": seated_bot_count,
    })


# ---------------------------------------------------------------------------
# Account list + create
# ---------------------------------------------------------------------------

@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Account).order_by(Account.id.desc()))
    accounts = result.scalars().all()

    # JSON response for API clients (Bearer auth)
    if _is_api_request(request):
        return JSONResponse([
            {
                "id": a.id, "nickname": a.nickname,
                "status": a.status.value, "wallet_balance": a.wallet_balance,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in accounts
        ])

    if not _is_authenticated(request):
        return _redirect_login("/admin/accounts")

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
    account = await session.get(Account, account_id)

    # JSON response for API clients (Bearer auth)
    if _is_api_request(request):
        if not account:
            return JSONResponse(
                {"detail": {"code": "NOT_FOUND", "message": "Account not found"}},
                status_code=404,
            )
        return JSONResponse({
            "id": account.id, "nickname": account.nickname,
            "status": account.status.value, "wallet_balance": account.wallet_balance,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        })

    if not _is_authenticated(request):
        return _redirect_login()

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


@router.post("/accounts/{account_id}/credentials/revoke-form")
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

@router.post("/accounts/{account_id}/grant-form")
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


@router.post("/accounts/{account_id}/deduct-form")
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


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

@router.get("/tables", response_class=HTMLResponse)
async def tables_page(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Table).order_by(Table.table_no))
    all_tables = result.scalars().all()

    # JSON response for API clients (Bearer auth)
    if _is_api_request(request):
        from sqlalchemy.orm import selectinload
        tables_json = []
        for t in all_tables:
            seats_r = await session.execute(select(TableSeat).where(TableSeat.table_id == t.id))
            seats = seats_r.scalars().all()
            seated = sum(1 for s in seats if s.seat_status != SeatStatus.EMPTY)
            tables_json.append({
                "id": t.id, "table_no": t.table_no, "status": t.status.value,
                "max_seats": t.max_seats, "small_blind": t.small_blind,
                "big_blind": t.big_blind, "buy_in": t.buy_in,
                "seated_count": seated,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            })
        return JSONResponse(tables_json)

    if not _is_authenticated(request):
        return _redirect_login("/admin/tables")

    tables_out = []
    for t in all_tables:
        # Count seated
        seats_r = await session.execute(select(TableSeat).where(TableSeat.table_id == t.id))
        seats = seats_r.scalars().all()
        seated = sum(1 for s in seats if s.seat_status != SeatStatus.EMPTY)

        # Active hand street
        hand_r = await session.execute(
            select(Hand).where(Hand.table_id == t.id, Hand.status == HandStatus.IN_PROGRESS)
        )
        hand = hand_r.scalar_one_or_none()
        tables_out.append({
            "table_no": t.table_no,
            "status": t.status.value,
            "seated_count": seated,
            "max_seats": t.max_seats,
            "current_hand_street": hand.street if hand else None,
        })

    return templates.TemplateResponse(request, "admin/tables.html", {
        "flash": None, "tables": tables_out,
    })


@router.post("/tables/create")
async def create_table_ui(
    request: Request,
    table_no: int = Form(...),
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    from app.services.table_service import create_table
    try:
        await create_table(session, table_no)
    except ValueError as e:
        pass  # Duplicate — just redirect

    return RedirectResponse(url="/admin/tables", status_code=302)


@router.post("/tables/{table_no}/pause-form")
async def pause_table_ui(
    request: Request, table_no: int, session: AsyncSession = Depends(get_session)
):
    if not _is_authenticated(request):
        return _redirect_login()
    from app.services.table_service import pause_table
    try:
        await pause_table(session, table_no)
    except Exception:
        pass
    return RedirectResponse(url=f"/admin/tables/{table_no}", status_code=302)


@router.post("/tables/{table_no}/resume-form")
async def resume_table_ui(
    request: Request, table_no: int, session: AsyncSession = Depends(get_session)
):
    if not _is_authenticated(request):
        return _redirect_login()
    from app.services.table_service import resume_table
    try:
        await resume_table(session, table_no)
    except Exception:
        pass
    return RedirectResponse(url=f"/admin/tables/{table_no}", status_code=302)


@router.post("/tables/{table_no}/close-form")
async def close_table_ui(
    request: Request, table_no: int, session: AsyncSession = Depends(get_session)
):
    if not _is_authenticated(request):
        return _redirect_login()
    from app.services.table_service import close_table
    try:
        await close_table(session, table_no)
    except Exception:
        pass
    return RedirectResponse(url=f"/admin/tables/{table_no}", status_code=302)


@router.get("/tables/{table_no}", response_class=HTMLResponse)
async def table_detail_ui(
    request: Request, table_no: int, session: AsyncSession = Depends(get_session)
):
    table_r = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_r.scalar_one_or_none()

    # JSON response for API clients (Bearer auth)
    if _is_api_request(request):
        if not table:
            return JSONResponse(
                {"detail": {"code": "NOT_FOUND", "message": "Table not found"}},
                status_code=404,
            )
        seats_r = await session.execute(
            select(TableSeat).where(TableSeat.table_id == table.id)
        )
        seats = [
            {
                "seat_no": s.seat_no,
                "account_id": s.account_id,
                "seat_status": s.seat_status.value,
                "stack": s.stack,
            }
            for s in seats_r.scalars().all()
        ]
        return JSONResponse({
            "id": table.id, "table_no": table.table_no, "status": table.status.value,
            "max_seats": table.max_seats, "small_blind": table.small_blind,
            "big_blind": table.big_blind, "buy_in": table.buy_in,
            "seats": seats,
            "created_at": table.created_at.isoformat() if table.created_at else None,
        })

    if not _is_authenticated(request):
        return _redirect_login()

    if not table:
        return HTMLResponse("Not found", status_code=404)

    seats_r = await session.execute(select(TableSeat).where(TableSeat.table_id == table.id))
    raw_seats = list(seats_r.scalars().all())

    acc_ids = [s.account_id for s in raw_seats if s.account_id]
    nickname_map: dict[int, str] = {}
    if acc_ids:
        acc_r = await session.execute(select(Account).where(Account.id.in_(acc_ids)))
        for a in acc_r.scalars().all():
            nickname_map[a.id] = a.nickname

    seats_out = [
        {
            "seat_no": s.seat_no,
            "nickname": nickname_map.get(s.account_id) if s.account_id else None,
            "stack": s.stack,
            "seat_status": s.seat_status.value,
        }
        for s in sorted(raw_seats, key=lambda x: x.seat_no)
    ]

    # Active hand with admin hole cards
    hand_r = await session.execute(
        select(Hand).where(Hand.table_id == table.id, Hand.status == HandStatus.IN_PROGRESS)
    )
    hand = hand_r.scalar_one_or_none()
    current_hand_data = None
    if hand:
        import json as _json
        players_r = await session.execute(
            select(HandPlayer).where(HandPlayer.hand_id == hand.id)
        )
        hp_list = list(players_r.scalars().all())
        player_data = []
        for hp in hp_list:
            player_data.append({
                "seat_no": hp.seat_no,
                "nickname": nickname_map.get(hp.account_id),
                "hole_cards": _json.loads(hp.hole_cards_json),
                "folded": hp.folded,
                "all_in": hp.all_in,
            })

        from app.core.pot_calculator import calculate_pots
        pot_input = [
            {"seat_no": p["seat_no"], "hand_contribution": hp.hand_contribution, "folded": hp.folded}
            for p, hp in zip(player_data, hp_list)
        ]
        raw_pot = calculate_pots(pot_input)
        total_pot = raw_pot["main_pot"] + sum(sp["amount"] for sp in raw_pot["side_pots"])

        current_hand_data = {
            "hand_no": hand.hand_no,
            "street": hand.street,
            "board": _json.loads(hand.board_json),
            "pot": total_pot,
            "current_bet": hand.current_bet,
            "players": player_data,
        }

    # Completed hand history (last 20)
    hist_r = await session.execute(
        select(Hand)
        .where(Hand.table_id == table.id, Hand.status == HandStatus.FINISHED)
        .order_by(Hand.id.desc())
        .limit(20)
    )
    from sqlalchemy.orm import selectinload
    hist_r = await session.execute(
        select(Hand)
        .where(Hand.table_id == table.id, Hand.status == HandStatus.FINISHED)
        .options(selectinload(Hand.result))
        .order_by(Hand.id.desc())
        .limit(20)
    )
    finished_hands = list(hist_r.scalars().all())

    import json as _json2
    hand_history = []
    for h in finished_hands:
        result_data = {}
        if h.result:
            try:
                result_data = _json2.loads(h.result.result_json)
            except Exception:
                pass
        awards = result_data.get("awards", {})
        winners = [int(k) for k in awards.keys()]
        hand_history.append({
            "hand_id": h.id,
            "hand_no": h.hand_no,
            "board": _json2.loads(h.board_json),
            "winners": winners,
            "started_at": h.started_at,
            "finished_at": h.finished_at,
        })

    return templates.TemplateResponse(request, "admin/table_detail.html", {
        "flash": None,
        "table": table,
        "seats": seats_out,
        "current_hand": current_hand_data,
        "hand_history": hand_history,
    })


# ---------------------------------------------------------------------------
# Bots
# ---------------------------------------------------------------------------

@router.get("/bots", response_class=HTMLResponse)
async def bots_page(request: Request, session: AsyncSession = Depends(get_session)):
    from app.services.bot_service import list_bots
    bots = await list_bots(session)

    # JSON response for API clients
    if _is_api_request(request):
        is_active_param = request.query_params.get("is_active")
        filtered = bots
        if is_active_param is not None:
            want_active = is_active_param.lower() in ("true", "1")
            filtered = [b for b in bots if b["is_active"] == want_active]
        return JSONResponse(filtered)

    if not _is_authenticated(request):
        return _redirect_login("/admin/bots")

    tables_r = await session.execute(select(Table).order_by(Table.table_no))
    tables = list(tables_r.scalars().all())

    return templates.TemplateResponse(request, "admin/bots.html", {
        "flash": None,
        "bots": bots,
        "tables": tables,
    })


@router.get("/tables/{table_no}/hands/{hand_id}", response_class=HTMLResponse)
async def hand_detail_ui(
    request: Request,
    table_no: int,
    hand_id: int,
    session: AsyncSession = Depends(get_session),
):
    if not _is_authenticated(request):
        return _redirect_login()

    table_r = await session.execute(select(Table).where(Table.table_no == table_no))
    table = table_r.scalar_one_or_none()
    if not table:
        return HTMLResponse("Not found", status_code=404)

    from sqlalchemy.orm import selectinload
    hand_r = await session.execute(
        select(Hand)
        .where(Hand.id == hand_id, Hand.table_id == table.id)
        .options(selectinload(Hand.result))
    )
    hand = hand_r.scalar_one_or_none()
    if not hand:
        return HTMLResponse("Not found", status_code=404)

    import json as _json
    players_r = await session.execute(
        select(HandPlayer).where(HandPlayer.hand_id == hand_id)
    )
    hp_list = list(players_r.scalars().all())

    acc_ids = [p.account_id for p in hp_list]
    acc_r = await session.execute(select(Account).where(Account.id.in_(acc_ids)))
    nm = {a.id: a.nickname for a in acc_r.scalars().all()}

    players_out = [
        {
            "seat_no": p.seat_no,
            "nickname": nm.get(p.account_id),
            "hole_cards": _json.loads(p.hole_cards_json),
            "starting_stack": p.starting_stack,
            "ending_stack": p.ending_stack,
            "folded": p.folded,
        }
        for p in hp_list
    ]

    result_data = {}
    if hand.result:
        try:
            result_data = _json.loads(hand.result.result_json)
        except Exception:
            pass
    awards = result_data.get("awards", {})
    result_out = {
        "winners": [int(k) for k in awards.keys()],
        "pot_summary": result_data.get("pot_view", {}),
    } if result_data else None

    actions = await get_hand_actions(session, hand_id)

    return templates.TemplateResponse(request, "admin/hand_detail.html", {
        "flash": None,
        "table_no": table_no,
        "hand": {
            "hand_no": hand.hand_no,
            "status": hand.status.value,
            "board": _json.loads(hand.board_json),
            "button_seat_no": hand.button_seat_no,
            "started_at": hand.started_at,
            "finished_at": hand.finished_at,
        },
        "players": players_out,
        "result": result_out,
        "actions": actions,
    })
