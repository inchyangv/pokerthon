#!/usr/bin/env python3
"""Reset all bots/tables and set up 3 tables with 3 bots each.

Usage:
    python scripts/reset_and_setup.py [BASE_URL] [ADMIN_PASSWORD]

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

# Bot layout: 3 tables × 3 bot types
BOT_TYPES = ["TAG", "LAG", "FISH"]
NUM_TABLES = 3


def ok(r: httpx.Response, label: str) -> dict:
    if r.status_code not in (200, 201, 204):
        print(f"  ✗ {label}: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    print(f"  ✓ {label}")
    return r.json() if r.content else {}


with httpx.Client(base_url=BASE_URL, headers=HEADERS, follow_redirects=True, timeout=30) as c:

    # ── 1. Delete all bots ────────────────────────────────────────────────
    print("\n[1] 봇 전체 삭제")
    bots = c.get("/admin/bots").json()
    if not bots:
        print("  (봇 없음)")
    for b in bots:
        ok(c.delete(f"/admin/accounts/{b['account_id']}"), f"봇 삭제: {b['display_name']}")

    # ── 2. Delete all tables ──────────────────────────────────────────────
    print("\n[2] 테이블 전체 삭제")
    tables = c.get("/admin/tables").json()
    if not tables:
        print("  (테이블 없음)")
    for t in tables:
        ok(c.delete(f"/admin/tables/{t['table_no']}"), f"테이블 {t['table_no']} 삭제")

    # ── 3. Create 3 tables ────────────────────────────────────────────────
    print("\n[3] 테이블 3개 생성")
    for n in range(1, NUM_TABLES + 1):
        ok(c.post("/admin/tables", json={"table_no": n}), f"테이블 {n} 생성")

    # ── 4. Create 3 bots per table and seat them ──────────────────────────
    print("\n[4] 테이블당 봇 3개 생성 및 착석")
    for table_no in range(1, NUM_TABLES + 1):
        for bot_type in BOT_TYPES:
            name = f"bot_{bot_type.lower()}_t{table_no}"
            # Create bot
            r = c.post("/admin/bots", json={"bot_type": bot_type, "display_name": name})
            bot = ok(r, f"봇 생성: {name} ({bot_type})")
            # Grant chips
            ok(
                c.post(f"/admin/accounts/{bot['account_id']}/grant",
                       json={"amount": 1000, "reason": "initial_setup"}),
                f"  칩 1000 지급: {name}",
            )
            # Seat bot (unseat first if bot runner auto-seated it elsewhere)
            r = c.post(f"/admin/bots/{bot['bot_id']}/seat", json={"table_no": table_no})
            if r.status_code == 409:
                c.post(f"/admin/bots/{bot['bot_id']}/unseat")
                r = c.post(f"/admin/bots/{bot['bot_id']}/seat", json={"table_no": table_no})
            ok(r, f"  착석: {name} → 테이블 {table_no}")

    print("\n✅ 셋업 완료: 테이블 3개, 테이블당 봇 3개 (TAG·LAG·FISH)")
