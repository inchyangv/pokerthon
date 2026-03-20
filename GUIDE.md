# Pokerthon 주최자 운영 가이드

**배포 URL:** `https://pokerthon-production.up.railway.app`

---

## 배포 상태 확인

```bash
curl https://pokerthon-production.up.railway.app/health
# → {"status": "ok"}
```

---

## 주요 페이지 목록

| 페이지 | URL | 설명 |
|--------|-----|------|
| **어드민 대시보드** | `/admin/` | 계정 수, 테이블 수, 전체 칩 현황 |
| **계정 목록** | `/admin/accounts` | 전체 계정 조회/생성 |
| **계정 상세** | `/admin/accounts/{id}` | 칩 지급, 키 발급, 원장 조회 |
| **테이블 목록** | `/admin/tables` | 테이블 생성/상태 확인 |
| **테이블 상세** | `/admin/tables/{table_no}` | 착석 현황, 진행 중인 핸드, 홀카드 포함 |
| **핸드 상세** | `/admin/tables/{table_no}/hands/{hand_id}` | 액션 로그, 결과 |
| **봇 관리** | `/admin/bots` | 봇 목록, 착석 배치 |
| **관전 로비** | `/viewer/` | 공개 관전 로비 (인증 불필요) |
| **관전 테이블** | `/viewer/tables/{table_no}` | 실시간 테이블 관전 |
| **리더보드** | `/viewer/leaderboard` | 칩/수익/승률 정렬 |
| **플레이그라운드** | `/playground/` | API 탐색기 |
| **서명 도구** | `/playground/signature` | HMAC 서명 계산기 |
| **퀵스타트** | `/playground/quickstart` | 참여자용 시작 가이드 |
| **API 문서** | `/docs` | Swagger UI |

---

## 어드민 패널 로그인

브라우저에서 `/admin/login` 접속 → `ADMIN_PASSWORD` 입력 (Railway 환경변수에 설정한 값).
세션 쿠키가 유지되므로 한 번 로그인하면 계속 쓸 수 있다.

**curl 등 API 클라이언트로 어드민 API 호출 시:**

```bash
curl -H "Authorization: Bearer {ADMIN_PASSWORD}" \
     https://pokerthon-production.up.railway.app/admin/accounts
```

---

## 참여자 계정 만들기

### UI

1. `/admin/accounts` 접속
2. 닉네임 입력 → `계정 생성` 버튼
3. 생성 직후 계정 상세 페이지로 이동됨 → 거기서 키 발급 이어서 진행

### API

```bash
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{"nickname": "팀이름"}' \
  https://pokerthon-production.up.railway.app/admin/accounts
# → {"id": 3, "nickname": "팀이름", "wallet_balance": 0, "status": "active"}
```

---

## API 키 발급 (credentials)

계정 생성 후 키를 발급해야 참여자가 API를 사용할 수 있다.
**`secret_key`는 발급 시 딱 한 번만 노출된다. 반드시 복사해서 참여자에게 전달할 것.**

### UI

1. `/admin/accounts/{id}` 접속
2. **API 키 발급** 버튼 클릭
3. 화면에 표시된 `secret_key` 복사 → 참여자에게 전달

### API

```bash
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  https://pokerthon-production.up.railway.app/admin/accounts/{account_id}/credentials
```

응답:
```json
{
  "api_key": "pk_abcd1234...",
  "secret_key": "sk_raw_xxxxxxxx...",
  "status": "active",
  "created_at": "..."
}
```

### 키 폐기 (재발급 필요 시 먼저 폐기)

```bash
# API
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  https://pokerthon-production.up.railway.app/admin/accounts/{account_id}/credentials/revoke

# UI: 계정 상세 페이지 → "키 폐기" 버튼
```

---

## 칩 지급

착석 바이인은 **40칩** 고정. 지갑에 40 이상 있어야 테이블에 앉을 수 있다.

### UI

`/admin/accounts/{id}` → **칩 지급** 폼 → 금액 입력 → Grant

### API

```bash
# 지급
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{"amount": 200, "reason": "initial_grant"}' \
  https://pokerthon-production.up.railway.app/admin/accounts/{account_id}/grant

# 차감
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{"amount": 40}' \
  https://pokerthon-production.up.railway.app/admin/accounts/{account_id}/deduct

# 원장 조회
curl -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  https://pokerthon-production.up.railway.app/admin/accounts/{account_id}/ledger
```

---

## 테이블 만들기

### UI

`/admin/tables` → 테이블 번호 입력 → 생성

### API

```bash
curl -s -X POST \
  -H "Authorization: Bearer {ADMIN_PASSWORD}" \
  -H "Content-Type: application/json" \
  -d '{"table_no": 1}' \
  https://pokerthon-production.up.railway.app/admin/tables
```

### 테이블 상태 제어

```bash
# 일시 정지 (진행 중인 핸드 종료 후 새 핸드 시작 안 함)
POST /admin/tables/{table_no}/pause

# 재개
POST /admin/tables/{table_no}/resume

# 영구 종료
POST /admin/tables/{table_no}/close
```

UI에서도 테이블 상세 페이지에 Pause / Resume / Close 버튼이 있다.

---

## 봇 관리

`/admin/bots` 에서 봇 목록 확인 및 특정 테이블에 배치할 수 있다.

봇 관련 환경변수:

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `BOT_ENABLED` | 봇 전체 활성화 여부 | `true` |
| `BOT_AUTO_SEED` | 시작 시 봇 자동 생성 | `false` |
| `BOT_INITIAL_CHIPS` | 봇 초기 칩 | `1000` |
| `BOT_POLL_INTERVAL` | 봇 폴링 주기(초) | `2.0` |

---

## 참여자에게 전달할 정보

각 참여자에게 아래 세 가지를 전달한다:

```
BASE_URL   = https://pokerthon-production.up.railway.app
API_KEY    = pk_xxxx...
SECRET_KEY = sk_raw_xxxx...   ← 발급 시 1회만 노출, 분실 시 재발급 필요
```

참여자 참고 페이지:
- 시작 가이드: `/playground/quickstart`
- API 탐색기: `/playground/`
- 서명 계산기: `/playground/signature`
- API 문서: `/docs`

---

## 환경변수 (Railway Variables)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 | — |
| `ADMIN_PASSWORD` | 어드민 패널/API 비밀번호 | `changeme` |
| `APP_ENCRYPTION_KEY` | 32자 암호화 키 | — |
| `ACTION_TIMEOUT_SECONDS` | 액션 타임아웃 (자동 폴드) | `600` (10분) |
| `TABLE_BUYIN` | 착석 바이인 칩 | `40` |
| `SMALL_BLIND` | 스몰 블라인드 | `1` |
| `BIG_BLIND` | 빅 블라인드 | `2` |

---

## 대회 시작 체크리스트

- [ ] Railway 배포 확인: `GET /health` → `{"status": "ok"}`
- [ ] 어드민 패널 로그인 확인: `/admin/`
- [ ] 테이블 생성 (table_no 1, 2, ... 원하는 수만큼)
- [ ] 참여자 계정 생성 (닉네임 = 팀명 권장)
- [ ] 각 계정에 API 키 발급 → `secret_key` 개별 전달
- [ ] 각 계정에 칩 지급 (최소 40칩 이상)
- [ ] 관전용 URL 공유: `/viewer/`
- [ ] 리더보드 URL 공유: `/viewer/leaderboard`
