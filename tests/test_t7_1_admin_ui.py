"""Tests for admin web UI — accounts, credentials, chips (T7.1)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.config import settings

ADMIN_PASSWORD = settings.ADMIN_PASSWORD


async def _login(client: AsyncClient) -> AsyncClient:
    """Log in and return the same client (cookie is stored)."""
    r = await client.post("/admin/login", data={"password": ADMIN_PASSWORD})
    assert r.status_code in (200, 302)
    return client


@pytest.mark.asyncio
async def test_login_page(client: AsyncClient):
    """로그인 페이지 접근."""
    r = await client.get("/admin/login")
    assert r.status_code == 200
    assert "로그인" in r.text or "Login" in r.text


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    """틀린 비밀번호 → 에러 메시지."""
    r = await client.post("/admin/login", data={"password": "wrong!"})
    assert r.status_code == 200
    assert "틀렸습니다" in r.text or "wrong" in r.text.lower()


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client: AsyncClient):
    """인증 없이 대시보드 접근 → 로그인으로 리다이렉트."""
    r = await client.get("/admin/", follow_redirects=False)
    assert r.status_code == 302
    assert "login" in r.headers["location"]


@pytest.mark.asyncio
async def test_dashboard_after_login(client: AsyncClient):
    """로그인 후 대시보드 정상 접근."""
    await _login(client)
    r = await client.get("/admin/")
    assert r.status_code == 200
    assert "Dashboard" in r.text


@pytest.mark.asyncio
async def test_accounts_list(client: AsyncClient):
    """계정 목록 페이지."""
    await _login(client)
    r = await client.get("/admin/accounts")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_create_account_via_ui(client: AsyncClient):
    """계정 생성 버튼 → 상세 페이지로 리다이렉트."""
    await _login(client)
    r = await client.post(
        "/admin/accounts/create",
        data={"nickname": "ui_test_bot"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "ui_test_bot" in r.text


@pytest.mark.asyncio
async def test_issue_credential_via_ui(client: AsyncClient):
    """키 발급 → SECRET_KEY 1회 표시."""
    await _login(client)
    # Create account first
    r = await client.post(
        "/admin/accounts/create",
        data={"nickname": "ui_cred_bot"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    # Extract account_id from URL
    acc_url = str(r.url)
    acc_id = acc_url.rstrip("/").split("/")[-1].split("?")[0]
    assert acc_id.isdigit()

    r2 = await client.post(
        f"/admin/accounts/{acc_id}/credentials/issue",
        follow_redirects=True,
    )
    assert r2.status_code == 200
    assert "sk_live_" in r2.text, "Secret key should be displayed on page"


@pytest.mark.asyncio
async def test_grant_chips_via_ui(client: AsyncClient):
    """칩 지급 폼 → 잔액 증가."""
    await _login(client)
    r = await client.post(
        "/admin/accounts/create",
        data={"nickname": "ui_chip_bot"},
        follow_redirects=True,
    )
    acc_url = str(r.url)
    acc_id = acc_url.rstrip("/").split("/")[-1].split("?")[0]

    r2 = await client.post(
        f"/admin/accounts/{acc_id}/grant-form",
        data={"amount": "100", "reason": "test"},
        follow_redirects=True,
    )
    assert r2.status_code == 200
    assert "100" in r2.text


@pytest.mark.asyncio
async def test_logout(client: AsyncClient):
    """로그아웃 → 세션 삭제."""
    await _login(client)
    r = await client.get("/admin/logout", follow_redirects=False)
    assert r.status_code == 302

    # Now dashboard should require auth again
    r2 = await client.get("/admin/", follow_redirects=False)
    assert r2.status_code == 302
