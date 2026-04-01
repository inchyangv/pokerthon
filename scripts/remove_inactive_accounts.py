#!/usr/bin/env python3
"""Remove inactive human accounts by nickname.

Usage:
    python scripts/remove_inactive_accounts.py [BASE_URL] [ADMIN_PASSWORD]

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

INACTIVE_NICKNAMES = {"곰", "독수리", "돌고래", "표범", "두루미", "너구리"}


with httpx.Client(base_url=BASE_URL, headers=HEADERS, follow_redirects=True, timeout=30) as c:
    # 1) List all accounts
    r = c.get("/admin/accounts")
    if r.status_code != 200:
        print(f"✗ 계정 목록 조회 실패: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    accounts = r.json()

    targets = [a for a in accounts if a["nickname"] in INACTIVE_NICKNAMES]
    found_names = {a["nickname"] for a in targets}
    missing = INACTIVE_NICKNAMES - found_names

    if missing:
        print(f"⚠ 찾을 수 없는 닉네임: {', '.join(sorted(missing))}")

    if not targets:
        print("삭제할 계정이 없습니다.")
        sys.exit(0)

    print(f"\n[삭제 대상] {len(targets)}개 계정:")
    for a in targets:
        print(f"  - {a['nickname']} (id={a['id']})")

    # 2) Delete each account
    print()
    deleted = 0
    for a in targets:
        r = c.delete(f"/admin/accounts/{a['id']}")
        if r.status_code in (200, 204):
            print(f"  ✓ 삭제 완료: {a['nickname']} (id={a['id']})")
            deleted += 1
        else:
            print(f"  ✗ 삭제 실패: {a['nickname']} → {r.status_code} {r.text[:200]}")
            sys.exit(1)

    print(f"\n✅ 완료: {deleted}개 비활성 계정 삭제됨")
