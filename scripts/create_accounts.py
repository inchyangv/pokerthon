#!/usr/bin/env python3
"""Create 16 human accounts with Korean animal nicknames and issue API keys.

Usage:
    python scripts/create_accounts.py [BASE_URL] [ADMIN_PASSWORD]

Outputs:
    scripts/accounts.csv
"""
import csv
import os
import sys

import httpx

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "https://pokerthon-production.up.railway.app"
PASSWORD = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ADMIN_PASSWORD", "")

if not PASSWORD:
    print("ERROR: ADMIN_PASSWORD not set.")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {PASSWORD}", "Content-Type": "application/json"}

ANIMALS = [
    "호랑이", "토끼", "여우", "곰",
    "늑대", "사슴", "독수리", "고래",
    "판다", "수달", "펭귄", "부엉이",
    "돌고래", "표범", "두루미", "너구리",
]

rows = []

with httpx.Client(base_url=BASE_URL, headers=HEADERS, follow_redirects=True, timeout=30) as c:
    for name in ANIMALS:
        # 1) Create account
        r = c.post("/admin/accounts", json={"nickname": name})
        if r.status_code not in (200, 201):
            print(f"✗ 계정 생성 실패: {name} → {r.status_code} {r.text[:200]}")
            sys.exit(1)
        acc = r.json()
        account_id = acc["id"]
        print(f"✓ 계정 생성: {name} (id={account_id})")

        # 2) Issue API credential
        r = c.post(f"/admin/accounts/{account_id}/credentials")
        if r.status_code not in (200, 201):
            print(f"✗ 키 발급 실패: {name} → {r.status_code} {r.text[:200]}")
            sys.exit(1)
        cred = r.json()
        print(f"  ✓ API 키 발급 완료")

        rows.append({
            "account_id": account_id,
            "nickname": name,
            "api_key": cred["api_key"],
            "secret_key": cred["secret_key"],
        })

# Write CSV
csv_path = os.path.join(os.path.dirname(__file__), "accounts.csv")
with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["account_id", "nickname", "api_key", "secret_key"])
    writer.writeheader()
    writer.writerows(rows)

print(f"\n✅ 완료: {len(rows)}개 계정 생성, CSV 저장 → {csv_path}")
