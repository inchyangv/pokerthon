#!/usr/bin/env python3
"""토너먼트 셋업: 봇/테이블 초기화 후 인간 참가자에게 칩 40 지급, 테이블 생성.

Usage:
    python scripts/setup_tournament.py [BASE_URL] [ADMIN_PASSWORD]

동작:
    1. 봇 전체 삭제
    2. 테이블 전체 삭제
    3. 인간 계정 칩 초기화 (0으로 deduct) + 40 지급
    4. 참가자 수에 맞게 테이블 생성
       - 9명 이하  → 테이블 1개
       - 10명 이상 → 테이블 2개 (5+5 또는 6+4 등 어드민이 직접 착석)

Defaults:
    BASE_URL         = https://pokerthon-production.up.railway.app
    ADMIN_PASSWORD   = $ADMIN_PASSWORD env var
"""
import os
import sys
import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://pokerthon-production.up.railway.app"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ADMIN_PASSWORD", "")

if not PASSWORD:
    print("ERROR: ADMIN_PASSWORD not set. Pass as 2nd arg or set env var.")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {PASSWORD}", "Content-Type": "application/json"}
TOURNAMENT_CHIPS = 40


def ok(r: httpx.Response, label: str) -> dict:
    if r.status_code not in (200, 201, 204):
        print(f"  ✗ {label}: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    print(f"  ✓ {label}")
    return r.json() if r.content else {}


with httpx.Client(base_url=BASE_URL, headers=HEADERS, follow_redirects=True, timeout=30) as c:

    # ── 1. 봇 전체 삭제 ─────────────────────────────────────────────────────
    print("\n[1] 봇 전체 삭제")
    bots = c.get("/admin/bots").json()
    if not bots:
        print("  (봇 없음)")
    for b in bots:
        ok(c.delete(f"/admin/accounts/{b['account_id']}"), f"봇 삭제: {b['display_name']}")

    # ── 2. 테이블 전체 삭제 ──────────────────────────────────────────────────
    print("\n[2] 테이블 전체 삭제")
    tables = c.get("/admin/tables").json()
    if not tables:
        print("  (테이블 없음)")
    for t in tables:
        ok(c.delete(f"/admin/tables/{t['table_no']}"), f"테이블 {t['table_no']} 삭제")

    # ── 3. 인간 계정 칩 초기화 + 40 지급 ────────────────────────────────────
    print("\n[3] 인간 계정 칩 초기화 및 지급")
    accounts = c.get("/admin/accounts").json()
    human_accounts = [a for a in accounts if not a.get("is_bot", False)]

    if not human_accounts:
        print("  (인간 계정 없음 — 먼저 create_accounts.py 실행)")
        sys.exit(1)

    for acc in human_accounts:
        acc_id = acc["id"]
        nickname = acc["nickname"]
        current_balance = acc.get("wallet_balance", 0)

        # 기존 잔액 전액 차감 (있을 경우)
        if current_balance > 0:
            ok(
                c.post(f"/admin/accounts/{acc_id}/deduct",
                       json={"amount": current_balance, "reason": "tournament_reset"}),
                f"  잔액 초기화: {nickname} (-{current_balance})",
            )

        # 토너먼트 칩 지급
        ok(
            c.post(f"/admin/accounts/{acc_id}/grant",
                   json={"amount": TOURNAMENT_CHIPS, "reason": "tournament_start"}),
            f"  칩 {TOURNAMENT_CHIPS} 지급: {nickname}",
        )

    # ── 4. 테이블 생성 ───────────────────────────────────────────────────────
    num_players = len(human_accounts)
    num_tables = 2 if num_players >= 10 else 1
    print(f"\n[4] 테이블 {num_tables}개 생성 (참가자 {num_players}명)")
    for n in range(1, num_tables + 1):
        ok(c.post("/admin/tables", json={"table_no": n}), f"테이블 {n} 생성")

    print(f"""
✅ 토너먼트 셋업 완료
   - 참가자: {num_players}명
   - 테이블: {num_tables}개
   - 칩: 인당 {TOURNAMENT_CHIPS}개

다음 단계:
   1. 각 참가자가 테이블에 착석 (POST /v1/private/tables/{{no}}/sit)
   2. 어드민에서 "핸드 시작" 버튼 클릭
   {'3. 10명 참가 시 탈락 후 어드민이 테이블 머지 필요' if num_tables > 1 else ''}
""")
