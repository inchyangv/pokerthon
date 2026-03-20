# TICKET.md

## 개요

PROJECT.md 기반 구현 티켓 목록.
마일스톤 순서: **M0 → M1 → M1.5 → M2 → M3 → M4 → M5 → M6 → M7**

각 티켓은 1 커밋 단위로 완결되어야 한다.

---

# HOTFIX — 칩 모델 재설계 + 게임 무결성 강화 (완료)

## HF-1: 칩 계정 자산 모델 + RNG 강화 + 카드 무결성 ✅ 완료

**Goal**: 착석 시 wallet 차감 방식 제거, 칩을 계정 자산으로 통합 관리. 덱 셔플 RNG를 OS 엔트로피 기반으로 교체. 카드 중복 발행 방지 검증 추가.

**설계 변경**:

### 칩 모델 (구 → 신)
- **구**: `wallet_balance` = 테이블에 없는 자유 칩. 착석 시 -40, 이석 시 +stack 반환.
- **신**: `wallet_balance` = 계정의 총 칩 (테이블 스택 포함). 착석/이석 시 wallet 불변. 핸드 종료 시 `ending_stack - starting_stack` delta를 wallet에 반영.

### 칩 보존 공식 변경
- **구**: `total = sum(wallets) + sum(stacks)`
- **신**: `total = sum(wallets)` (stacks은 wallet의 부분집합, 별도 합산 불가)

**변경 파일**:
- `app/core/deck.py`: `random.shuffle` → `random.SystemRandom().shuffle` (OS /dev/urandom 기반). `__init__` 및 `from_json`에서 52장 고유 카드 무결성 검증 추가.
- `app/services/chip_service.py`: `apply_game_delta(session, account_id, delta, hand_id)` 추가 (HAND_WIN / HAND_LOSS 원장 기록).
- `app/services/seat_service.py`: `sit()`에서 `transfer_to_table()` 제거. `stand()`에서 `transfer_from_table()` 제거.
- `app/services/hand_completion.py`: `_record_cashout()` 제거. 핸드 종료 시 모든 참가자에 `apply_game_delta()` 적용.
- 테스트 파일 다수: 칩 보존 어서션 업데이트.

**주의사항**:
- `TABLE_BUYIN`, `TABLE_CASHOUT` enum 값은 DB에 유지 (기존 원장 데이터 하위 호환). 신규 기록은 생성되지 않음.
- Alembic 마이그레이션 불필요 (새 enum 값 없음).

**Commit**: `refactor(chips): unified wallet model — no buy-in deduction, game delta on hand complete`

---

---

# M0 — Project Bootstrap

## T0.1: FastAPI 프로젝트 스캐폴드

**Goal**: 프로젝트 디렉터리 구조, 의존성, 설정 시스템을 갖춘 빈 FastAPI 앱을 만든다.

**Scope**:
- `pyproject.toml` (또는 `requirements.txt`)
- `app/` 디렉터리 구조
- `app/main.py` (FastAPI app 인스턴스)
- `app/config.py` (Pydantic Settings)
- `.env.example`
- `.gitignore`

**AC**:
- [ ] `pyproject.toml`에 Python 3.12, FastAPI, Uvicorn, SQLAlchemy, Alembic, Pydantic, asyncpg, python-dotenv 등 핵심 의존성이 정의됨
- [ ] `app/main.py`에 FastAPI 인스턴스가 존재하고 `uvicorn app.main:app`으로 기동 가능
- [ ] `app/config.py`에 Pydantic `BaseSettings` 기반 설정 클래스가 존재하며 `PORT`, `DATABASE_URL`, `ADMIN_PASSWORD`, `APP_ENCRYPTION_KEY`, `ACTION_TIMEOUT_SECONDS`(기본 600), `TABLE_BUYIN`(기본 40), `SMALL_BLIND`(기본 1), `BIG_BLIND`(기본 2) 환경변수를 읽음
- [ ] `.env.example`에 모든 필수 환경변수가 예시값과 함께 나열됨
- [ ] `.gitignore`에 `__pycache__`, `.env`, `*.pyc`, `.venv/`, `alembic/versions/*.pyc` 등 포함
- [ ] 디렉터리 구조가 다음과 같음:
  ```
  app/
    __init__.py
    main.py
    config.py
    models/
    schemas/
    services/
    api/
      admin/
      public/
      private/
    middleware/
    core/
  ```
- [ ] `python -c "from app.main import app; print(app.title)"` 실행 시 에러 없음

**Commit**: `feat(scaffold): init FastAPI project with directory structure and settings`

---

## T0.2: DB 연결 + Alembic + 전체 모델 + 마이그레이션

**Goal**: SQLAlchemy 모델 전체 정의, Alembic 초기 마이그레이션, DB 연결, 헬스체크 엔드포인트를 구성한다.

**Deps**: T0.1

**Scope**:
- `app/database.py`
- `app/models/` (전체 테이블 모델)
- `alembic/` (설정 + 초기 마이그레이션)
- `alembic.ini`
- `app/api/health.py`
- `docker-compose.yml` (로컬 개발용 PostgreSQL)

**AC**:
- [ ] `docker-compose.yml`에 PostgreSQL 서비스가 정의되어 `docker compose up -d` 로 기동 가능
- [ ] `app/database.py`에 async SQLAlchemy engine + session factory가 구현됨
- [ ] 다음 모델이 모두 정의됨 (PROJECT.md §8 기준):
  - `Account` — id, nickname(unique), status(ACTIVE/BLOCKED), wallet_balance, created_at, updated_at
  - `ApiCredential` — id, account_id(FK), api_key(unique), secret_hash, status(ACTIVE/REVOKED), created_at, revoked_at, last_used_at
  - `ApiNonce` — id, api_key, nonce, timestamp, unique(api_key, nonce)
  - `ChipLedger` — id, account_id(FK), delta, balance_after, reason_type, reason_text, ref_type, ref_id, created_at
  - `Table` — id, table_no(unique), status, max_seats(=9), small_blind(=1), big_blind(=2), buy_in(=40), created_at, updated_at
  - `TableSeat` — id, table_id(FK), seat_no(1~9), account_id(FK nullable), seat_status(EMPTY/SEATED/LEAVING_AFTER_HAND), stack, joined_at, updated_at, unique(table_id, seat_no)
  - `Hand` — id, table_id(FK), hand_no, status(IN_PROGRESS/FINISHED), button_seat_no, small_blind_seat_no, big_blind_seat_no, street, board_json, deck_json, current_bet, action_seat_no, action_deadline_at, deal_index, started_at, finished_at
  - `HandPlayer` — id, hand_id(FK), account_id(FK), seat_no, hole_cards_json, starting_stack, ending_stack, folded, all_in, round_contribution, hand_contribution
  - `HandAction` — id, hand_id(FK), seq, street, actor_account_id(nullable), actor_seat_no(nullable), action_type, amount, amount_to, payload_json, is_system_action, created_at
  - `HandResult` — id, hand_id(FK), result_json, created_at
  - `TableSnapshot` — table_id(PK), version, snapshot_json, updated_at
- [ ] `alembic init alembic` 후 `env.py`에 async 지원 설정 완료
- [ ] `alembic revision --autogenerate -m "initial"` → `alembic upgrade head` 로 전체 테이블 생성 가능
- [ ] `GET /health` 가 `{"status": "ok", "db": "connected"}` 응답 (200)
- [ ] DB 연결 실패 시 `GET /health`가 `{"status": "error", "db": "disconnected"}` 응답 (503)

**Commit**: `feat(db): add SQLAlchemy models, Alembic migration, health check, docker-compose`

---

# M1 — Accounts & Auth Foundation

## T1.1: 관리자 인증 미들웨어 + 계정 CRUD

**Goal**: Admin Bearer 인증과 계정 생성/조회/목록 API를 구현한다.

**Deps**: T0.2

**Scope**:
- `app/middleware/admin_auth.py`
- `app/services/account_service.py`
- `app/schemas/account.py`
- `app/api/admin/accounts.py`

**AC**:
- [ ] `/admin/*` 엔드포인트에 `Authorization: Bearer {ADMIN_PASSWORD}` 헤더 검증 미들웨어 적용
- [ ] 인증 실패 시 `401 {"error": {"code": "UNAUTHORIZED", "message": "..."}}`
- [ ] `POST /admin/accounts` — `{"nickname": "bot_alpha"}` → 계정 생성, 응답에 account_id 포함
- [ ] 닉네임 중복 시 `409 {"error": {"code": "CONFLICT", "message": "..."}}`
- [ ] 닉네임 빈 문자열 또는 미입력 시 `422`
- [ ] 계정 생성 시 `wallet_balance = 0`, `status = ACTIVE`
- [ ] `GET /admin/accounts` — 전체 계정 목록 반환 (id, nickname, status, wallet_balance, created_at)
- [ ] `GET /admin/accounts/{account_id}` — 특정 계정 상세 반환
- [ ] 존재하지 않는 account_id 조회 시 `404`
- [ ] 단위 테스트: 계정 생성 → 중복 생성 → 목록 조회 → 상세 조회

**Commit**: `feat(accounts): add admin auth middleware and account CRUD API`

---

## T1.2: API 키 발급 / 폐기

**Goal**: 계정별 API_KEY / SECRET_KEY 생성, 폐기, 재발급 API를 구현한다.

**Deps**: T1.1

**Scope**:
- `app/services/credential_service.py`
- `app/schemas/credential.py`
- `app/api/admin/credentials.py`
- `app/core/crypto.py`

**AC**:
- [ ] `POST /admin/accounts/{account_id}/credentials` → API_KEY(`pk_live_` 접두어 + 랜덤) + SECRET_KEY(`sk_live_` 접두어 + 랜덤) 생성
- [ ] SECRET_KEY는 응답에 **1회만** 평문 반환. DB에는 **해시(SHA-256 또는 bcrypt)** 로 저장
- [ ] 기존 ACTIVE 키가 있으면 자동 REVOKE 후 새 키쌍 생성
- [ ] `POST /admin/accounts/{account_id}/credentials/revoke` → 활성 키를 REVOKED 처리, `revoked_at` 기록
- [ ] 활성 키가 없는 상태에서 revoke 호출 시 `404` 또는 적절한 에러
- [ ] `GET /admin/accounts/{account_id}/credentials` → 키 목록 반환 (api_key, status, created_at, revoked_at). SECRET_KEY 원문은 미포함
- [ ] 존재하지 않는 account_id 시 `404`
- [ ] 단위 테스트: 키 생성 → 검증 → 폐기 → 재발급 → 구키로 검증 실패

**Commit**: `feat(credentials): add API key generation, revocation, and re-issue`

---

## T1.3: HMAC-SHA256 서명 검증 미들웨어

**Goal**: 플레이어 API(`/v1/private/*`) 에 HMAC-SHA256 서명 인증을 적용한다.

**Deps**: T1.2

**Scope**:
- `app/middleware/hmac_auth.py`
- `app/services/nonce_service.py`
- `app/core/signature.py`

**AC**:
- [ ] `/v1/private/*` 요청에 `X-API-KEY`, `X-TIMESTAMP`, `X-NONCE`, `X-SIGNATURE` 헤더 필수
- [ ] 서명 원문(canonical string) 생성 규칙 구현:
  ```
  {timestamp}\n{nonce}\n{method}\n{path}\n{sorted_query_string}\n{sha256(body)}
  ```
- [ ] `signature = hex(HMAC_SHA256(secret_key_raw, canonical_string))` 검증
- [ ] 빈 body(GET 등)일 때 body SHA-256 = `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- [ ] 쿼리 파라미터는 키 알파벳 오름차순 정렬 후 `key1=value1&key2=value2` 형태
- [ ] 타임스탬프 ±300초 범위 벗어나면 `401`
- [ ] nonce 중복 사용 시 `401` (또는 `409`)
- [ ] 폐기된(REVOKED) 키로 요청 시 `401`
- [ ] 서명 불일치 시 `401`
- [ ] 인증 성공 시 요청 컨텍스트에 `account_id` 주입
- [ ] nonce는 DB(`api_nonces`)에 저장. unique(api_key, nonce) 제약으로 중복 방지
- [ ] `api_credentials.last_used_at` 갱신
- [ ] `/v1/public/*` 경로는 인증 미적용 (통과)
- [ ] 단위 테스트: 정상 서명 → 위조 서명 → 만료 타임스탬프 → nonce 재사용 → 폐기된 키 (총 5개 케이스)
- [ ] 클라이언트 측 서명 생성 헬퍼 함수도 `app/core/signature.py`에 포함 (테스트용)

**Commit**: `feat(auth): add HMAC-SHA256 signature verification middleware`

---

# M1.5 — Chip Management

## T1.5.1: 칩 원장 서비스 + 관리자 칩 API

**Goal**: 칩 지급/차감 서비스와 원장 기록, 관리자 API를 구현한다.

**Deps**: T1.1

**Scope**:
- `app/services/chip_service.py`
- `app/schemas/chip.py`
- `app/api/admin/chips.py`

**AC**:
- [ ] `POST /admin/accounts/{account_id}/grant` — `{"amount": 200, "reason": "league_round_1"}` → 지갑 잔액 +200
- [ ] `POST /admin/accounts/{account_id}/deduct` — `{"amount": 50, "reason": "penalty"}` → 지갑 잔액 -50
- [ ] `amount`는 양의 정수만 허용. 0 이하이면 `422`
- [ ] 차감 시 `wallet_balance < amount` 이면 `422 {"error": {"code": "INSUFFICIENT_BALANCE", ...}}`
- [ ] 지갑 잔액은 절대 음수가 되지 않음
- [ ] 모든 칩 변동은 `chip_ledger`에 기록: delta, balance_after, reason_type(`ADMIN_GRANT`/`ADMIN_DEDUCT`), reason_text
- [ ] `GET /admin/accounts/{account_id}/ledger` — 해당 계정의 칩 원장 조회 (최신순)
- [ ] 원장 레코드에 `ref_type`, `ref_id` 포함 (이 시점에서는 null 가능)
- [ ] `chip_service` 내부에 `grant()`, `deduct()`, `transfer_to_table()`, `transfer_from_table()` 메서드 시그니처 정의 (table 관련은 M2에서 구현)
- [ ] DB 트랜잭션 내에서 `wallet_balance` 업데이트 + ledger insert가 원자적으로 수행됨
- [ ] 단위 테스트: 지급 → 잔액 확인 → 차감 → 잔액 확인 → 초과 차감 에러 → 원장 개수 확인

**Commit**: `feat(chips): add chip ledger service and admin grant/deduct API`

---

# M2 — Tables & Seating

## T2.1: 테이블 CRUD + 상태 전이

**Goal**: 테이블 생성, 상태 전이(OPEN/PAUSED/CLOSED), 관리자 API를 구현한다.

**Deps**: T1.1

**Scope**:
- `app/services/table_service.py`
- `app/schemas/table.py`
- `app/api/admin/tables.py`

**AC**:
- [ ] `POST /admin/tables` — `{"table_no": 1}` → 테이블 생성. status=`OPEN`, max_seats=9, seat 레코드 9개(1~9, 모두 EMPTY) 동시 생성
- [ ] `table_no` 중복 시 `409`
- [ ] `POST /admin/tables/{table_no}/pause` → OPEN→PAUSED 전이. 이미 PAUSED/CLOSED면 `409`
- [ ] `POST /admin/tables/{table_no}/resume` → PAUSED→OPEN 전이. PAUSED가 아니면 `409`
- [ ] `POST /admin/tables/{table_no}/close` → OPEN 또는 PAUSED→CLOSED 전이. 이미 CLOSED면 `409`
- [ ] CLOSED 테이블에서 seated 플레이어가 있으면 스택을 지갑으로 반환 + `TABLE_CASHOUT` 원장 기록 + 좌석 EMPTY 처리
- [ ] CLOSED 이후 재오픈 시도 시 `409`
- [ ] `GET /admin/tables` — 전체 테이블 목록
- [ ] `GET /admin/tables/{table_no}` — 테이블 상세 + 좌석 현황
- [ ] 존재하지 않는 table_no 시 `404`
- [ ] 단위 테스트: 생성 → pause → resume → close → 재open 실패, 좌석 9개 확인, close 시 칩 반환

**Commit**: `feat(tables): add table CRUD with state machine and admin API`

---

## T2.2: 착석 / 이석 서비스 + 플레이어 API

**Goal**: 플레이어의 테이블 착석/이석 로직과 칩 흐름(지갑↔스택)을 구현한다.

**Deps**: T2.1, T1.5.1, T1.3

**Scope**:
- `app/services/seat_service.py`
- `app/schemas/seat.py`
- `app/api/private/tables.py`

**AC**:
- [ ] `POST /v1/private/tables/{table_no}/sit` — `{"seat_no": 4}` (선택) → 착석
- [ ] 착석 시: 지갑에서 `buy_in`(40) 차감 → 테이블 스택 40 설정 → `TABLE_BUYIN` 원장 기록
- [ ] `seat_no` 미지정 시 빈 좌석 중 가장 낮은 번호 자동 배정
- [ ] 에러 케이스:
  - 지갑 잔액 < 40 → `422 INSUFFICIENT_BALANCE`
  - 이미 다른 테이블에 앉아 있음 → `409 CONFLICT` ("already seated at table X")
  - 같은 테이블에 이미 앉아 있음 → `409 CONFLICT`
  - 지정 좌석 사용 중 → `409 SEAT_TAKEN`
  - 빈 좌석 없음 → `422 TABLE_FULL`
  - 테이블 status가 OPEN이 아님 → `422 INVALID_ACTION`
- [ ] `POST /v1/private/tables/{table_no}/stand` → 이석 요청
- [ ] 핸드 미진행 중 → 즉시 이석: 좌석 EMPTY, 스택→지갑 반환, `TABLE_CASHOUT` 원장
- [ ] 핸드 진행 중 + 플레이어가 참여 중 → `seat_status = LEAVING_AFTER_HAND`, 즉시 이석하지 않음
- [ ] 핸드 진행 중 + 플레이어가 미참여(핸드 중 착석) → 즉시 이석
- [ ] 한 계정 동시 1테이블만 착석 가능 (DB unique 또는 서비스 레벨 검증)
- [ ] 좌석 번호 범위: 1~9, 범위 밖이면 `422`
- [ ] 단위 테스트: 정상 착석 → 잔액 차감 확인 → 이석 → 잔액 복원 확인 → 중복 착석 에러 → 잔액 부족 에러 → 좌석 지정 → 빈좌석 자동배정

**Commit**: `feat(seating): add sit/stand logic with chip flow and player API`

---

## T2.3: 공개 테이블 API + 플레이어 계정 API

**Goal**: 인증 불필요한 테이블 공개 조회와 플레이어 자기 정보 조회 API를 구현한다.

**Deps**: T2.2

**Scope**:
- `app/api/public/tables.py`
- `app/api/private/me.py`
- `app/schemas/table_public.py`

**AC**:
- [ ] `GET /v1/public/tables` — 전체 테이블 목록 (table_no, status, 착석 인원, max_seats)
- [ ] `GET /v1/public/tables/{table_no}` — 테이블 공개 상태 (좌석별: seat_no, nickname, stack, seat_status). 홀카드 미포함
- [ ] 존재하지 않는 table_no → `404`
- [ ] `GET /v1/private/me` — 자기 계정 정보 (account_id, nickname, wallet_balance, current_table_no). 인증 필요
- [ ] `current_table_no`는 현재 앉아 있는 테이블 번호. 미착석 시 `null`
- [ ] public API는 인증 없이 접근 가능
- [ ] 단위 테스트: 테이블 2개 생성 → 목록 확인 → 상세 조회 → me 조회

**Commit**: `feat(public-api): add public table endpoints and player me endpoint`

---

# M3 — Core Game Engine

## T3.1: 카드 / 덱 / 핸드 평가기

**Goal**: 카드 표현, 덱 셔플, 7장 중 최고 5장 핸드 평가기를 순수 도메인 로직으로 구현한다.

**Deps**: T0.1

**Scope**:
- `app/core/card.py`
- `app/core/deck.py`
- `app/core/evaluator.py`

**AC**:
- [ ] `Card` 클래스: 2글자 문자열 표기 (`As`, `Td`, `2c` 등). rank + suit 속성
- [ ] 랭크 순서: 2 < 3 < ... < 9 < T < J < Q < K < A
- [ ] 수트: `s`, `h`, `d`, `c` — 수트 간 우열 없음
- [ ] `Deck` 클래스: 52장 표준 덱. `shuffle()` (Fisher-Yates), `deal(n)` (n장 딜), `deal_index` 추적
- [ ] 덱 직렬화/역직렬화: JSON 배열로 변환 가능 (복구용)
- [ ] `HandEvaluator`: 7장 카드에서 최고 5장 조합 평가
  - 반환: (hand_rank, tiebreakers) 튜플. hand_rank는 정수 (1=High Card ~ 10=Royal Flush 또는 역순, 일관되면 됨)
  - 비교 가능: evaluator 결과끼리 비교하면 승/패/무 판단 가능
- [ ] 지원 핸드 랭킹 (높은 순): Royal Flush, Straight Flush, Four of a Kind, Full House, Flush, Straight, Three of a Kind, Two Pair, One Pair, High Card
- [ ] A는 하이(A-K-Q-J-T) + 로우(5-4-3-2-A) 스트레이트 모두 인식
- [ ] 5-4-3-2-A (wheel) = 가장 낮은 스트레이트
- [ ] 단위 테스트 (최소 15개 케이스):
  - Royal Flush 인식
  - Straight Flush 인식
  - Four of a Kind 인식 + 키커
  - Full House 인식 + 트리플 우선 비교
  - Flush 인식 + 키커 비교
  - Straight 인식 (일반 + wheel)
  - Three of a Kind
  - Two Pair + 키커
  - One Pair + 키커
  - High Card
  - 7장에서 최고 5장 정확 선택
  - 동일 랭크 타이브레이커 비교
  - 완전 동점(split pot) 판별
  - Wheel vs 6-high straight
  - Flush vs Straight (Flush 승)

**Commit**: `feat(cards): add card, deck, and 7-card hand evaluator with tests`

---

## T3.2: 핸드 시작 — 블라인드 포스트 + 딜링

**Goal**: 핸드 시작 로직을 구현한다: 버튼 결정, SB/BB 포스트, 홀카드 딜, 첫 액션 좌석 결정.

**Deps**: T3.1, T2.2

**Scope**:
- `app/services/hand_service.py`
- `app/services/game_engine.py` (또는 `hand_manager.py`)

**AC**:
- [ ] `start_hand(table_id)` → 새 핸드 생성, DB에 `Hand` + `HandPlayer` 레코드 insert
- [ ] 스택 > 0인 SEATED 플레이어만 핸드 참가 (LEAVING_AFTER_HAND도 포함)
- [ ] 2명 미만이면 핸드 시작하지 않음
- [ ] **버튼 결정**:
  - 테이블 최초 핸드: 가장 낮은 seat_no의 활성 좌석이 버튼
  - 이후 핸드: 이전 버튼에서 시계 방향(seat_no 오름차순 순환) 다음 활성 좌석
- [ ] **SB/BB 결정**:
  - 3인 이상: 버튼 다음 활성 좌석 = SB, 그 다음 = BB
  - 2인(헤즈업): 버튼 = SB, 상대 = BB
- [ ] **블라인드 포스트**:
  - SB 포스트: `small_blind`(1)만큼 스택에서 차감 → `round_contribution`, `hand_contribution` 반영
  - BB 포스트: `big_blind`(2)만큼 차감 → 동일 반영
  - 스택 < 블라인드 금액이면 가진 만큼만 포스트 (올인 상태)
  - `HandAction` 로그: `POST_SMALL_BLIND`, `POST_BIG_BLIND` (is_system_action=true)
- [ ] **홀카드 딜**:
  - 덱 셔플 후 각 참가자에게 2장 딜
  - `hand_players.hole_cards_json`에 저장
  - `HandAction` 로그: `DEAL_HOLE` (is_system_action=true)
  - `hands.deck_json`, `hands.deal_index` 저장 (복구용)
- [ ] **첫 액션 좌석**:
  - 프리플랍: BB 다음 활성(fold/all-in 아닌) 좌석 = UTG
  - 헤즈업 프리플랍: 버튼(SB)이 먼저
  - `hands.action_seat_no`, `hands.action_deadline_at` (현재 + 600초) 설정
- [ ] `hands.street = 'preflop'`, `hands.current_bet = big_blind`, `hands.status = 'IN_PROGRESS'`
- [ ] Hand, HandPlayer 데이터가 모두 DB에 저장됨
- [ ] 단위 테스트:
  - 3인 핸드 시작 → 버튼/SB/BB 좌석 확인
  - 2인 헤즈업 → 버튼=SB 확인, 프리플랍 첫 액션=버튼
  - SB 스택 1일 때 → 1만 포스트, 올인 확인
  - 연속 핸드 → 버튼 회전 확인
  - 액션 로그에 POST_SMALL_BLIND, POST_BIG_BLIND, DEAL_HOLE 존재

**Commit**: `feat(hand-start): implement hand initialization with blinds, dealing, and button rotation`

---

## T3.3: 베팅 라운드 엔진 — 액션 처리

**Goal**: 개별 액션(FOLD/CHECK/CALL/BET_TO/RAISE_TO/ALL_IN) 처리와 유효성 검증 로직을 구현한다.

**Deps**: T3.2

**Scope**:
- `app/services/action_service.py`
- `app/core/action_validator.py`

**AC**:
- [ ] `process_action(hand_id, account_id, action_type, amount=None)` 메서드 구현
- [ ] **FOLD**: 해당 플레이어 `folded = True`. 다음 액터로 이동
- [ ] **CHECK**: `to_call == 0` 일 때만 허용. 아니면 `422 INVALID_ACTION`
- [ ] **CALL**: `to_call` 만큼 스택 차감, `round_contribution` + `hand_contribution` 증가. 스택 < to_call이면 남은 스택 전부 투입 (콜 올인), `all_in = True`
- [ ] **BET_TO(amount)**: 현재 스트리트에 베팅 없을 때만 허용 (current_bet == 0 또는 프리플랍에서 BB만 있는 상태는 bet이 아니라 raise). amount >= big_blind. 이미 베팅 있으면 `422`
- [ ] **RAISE_TO(amount)**: 현재 최고 베팅이 있을 때만 허용. amount >= `ceil(current_bet * 1.5)`. 베팅 없으면 `422`
- [ ] **ALL_IN**: 남은 스택 전부 투입. 상황 무관 항상 유효
- [ ] 자기 턴이 아닌데 액션 제출 → `422 INVALID_ACTION`
- [ ] 이미 folded/all-in인 플레이어가 액션 → `422`
- [ ] 액션 처리 후 `hand_actions`에 로그 insert (seq 자동 증가)
- [ ] `current_bet` 업데이트 (BET_TO, RAISE_TO, ALL_IN으로 현재 최고 베팅 초과 시)
- [ ] **Raise reopen 규칙**: 최소 레이즈(`ceil(current_bet * 1.5)`)를 충족하는 올인/레이즈만 다른 플레이어의 추가 레이즈 권한을 염. 숏 올인은 reopen 안 함
- [ ] 모든 칩 연산은 정수
- [ ] 단위 테스트:
  - FOLD → folded 확인
  - CHECK 가능/불가능 상황
  - CALL → contribution 확인
  - CALL 올인 (스택 < to_call)
  - BET_TO 정상 + 최소 미달 에러 + 이미 bet 있을 때 에러
  - RAISE_TO 정상 + 최소 미달 에러 + bet 없을 때 에러
  - ALL_IN → 스택 전액 투입 확인
  - 턴 아닌 플레이어 액션 → 에러

**Commit**: `feat(betting): implement action processing with validation rules`

---

## T3.4: 리걸 액션 계산기

**Goal**: 현재 게임 상태에서 특정 플레이어가 취할 수 있는 합법적 액션 목록을 계산한다.

**Deps**: T3.3

**Scope**:
- `app/core/legal_actions.py`

**AC**:
- [ ] `get_legal_actions(hand, hand_player)` → 가능한 액션 목록 반환
- [ ] 반환 형식: `[{"type": "FOLD"}, {"type": "CALL", "amount": 2}, {"type": "RAISE_TO", "min": 3, "max": 38}, ...]`
- [ ] 자기 턴이 아니면 빈 배열
- [ ] **FOLD**: 항상 가능 (자기 턴일 때)
- [ ] **CHECK**: `to_call == 0`일 때만
- [ ] **CALL**: `to_call > 0`일 때. amount = min(to_call, stack)
- [ ] **BET_TO**: current_bet == 0 (프리플랍 BB 이후 제외)일 때. min = big_blind, max = stack
- [ ] **RAISE_TO**: current_bet > 0일 때. min = ceil(current_bet * 1.5), max = stack + round_contribution
  - 스택이 min_raise 미만이면 RAISE_TO는 제외 (대신 ALL_IN만 가능)
- [ ] **ALL_IN**: 스택 > 0이면 항상 가능
- [ ] `to_call` 계산: `current_bet - round_contribution` (음수면 0)
- [ ] `min_raise_to` 계산: `ceil(current_bet * 1.5)`
- [ ] `max_raise_to` 계산: `stack + round_contribution` (총액 기준)
- [ ] 단위 테스트 (최소 10개):
  - 프리플랍 UTG → FOLD, CALL(2), RAISE_TO(min=3, max=...), ALL_IN
  - BB after limpers → FOLD, CHECK, RAISE_TO, ALL_IN
  - 플랍 첫 액션 → FOLD, CHECK, BET_TO(min=2, max=stack), ALL_IN
  - 스택 1칩일 때 → FOLD, ALL_IN만 (CALL/RAISE 불가)
  - 스택 = to_call일 때 → FOLD, CALL(=ALL_IN), ALL_IN
  - 올인 플레이어 → 빈 배열
  - 폴드 플레이어 → 빈 배열
  - min_raise_to 계산: bet=2 → 3, bet=10 → 15, bet=17 → 26

**Commit**: `feat(legal-actions): implement legal action calculator with min/max raise`

---

## T3.5: 베팅 라운드 종료 판단 + 스트리트 진행

**Goal**: 베팅 라운드 완료 조건 판단, 다음 스트리트(flop/turn/river) 전환, 보드 카드 딜링을 구현한다.

**Deps**: T3.3

**Scope**:
- `app/services/round_service.py` (또는 `game_engine.py` 확장)

**AC**:
- [ ] **다음 액터 결정**: 현재 액터의 시계 방향(seat_no 오름차순 순환) 다음 활성(not folded, not all-in) 좌석
- [ ] **베팅 라운드 종료 조건** (하나라도 만족 시):
  - 활성 플레이어가 모두 동일 `round_contribution`에 도달 + 최소 1회 이상 액션
  - 활성 플레이어가 0명 (전원 fold/all-in)
  - 활성 플레이어가 1명이고 그 플레이어의 `round_contribution >= current_bet`
  - 전원 체크 완료
- [ ] **라운드 종료 시 처리**:
  - 모든 참가자의 `round_contribution = 0` 리셋
  - `hands.current_bet = 0` 리셋
- [ ] **스트리트 전환**:
  - preflop → flop: 보드에 3장 딜. `DEAL_FLOP` 액션 로그
  - flop → turn: 보드에 1장 추가. `DEAL_TURN` 액션 로그
  - turn → river: 보드에 1장 추가. `DEAL_RIVER` 액션 로그
  - river 종료 → showdown으로 전환
- [ ] **포스트플랍 첫 액션**: 버튼 다음 활성 좌석 (헤즈업: BB(=비버튼))
- [ ] **전원 올인 또는 1명만 액션 가능 시**: 나머지 보드 카드 즉시 딜 후 showdown
- [ ] **한 명만 남으면**: 즉시 핸드 종료 (fold 승리). showdown 건너뜀
- [ ] `hands.board_json`, `hands.street`, `hands.deal_index` 업데이트 후 DB 저장
- [ ] 단위 테스트:
  - 3인 프리플랍: 전원 콜 → 라운드 종료 → flop 딜 확인
  - flop: 체크 라운드 → turn 딜 확인
  - 2인: 한 명 폴드 → 즉시 핸드 종료
  - 전원 올인 → 남은 보드 즉시 딜
  - round_contribution 리셋 확인
  - 포스트플랍 액션 순서 확인

**Commit**: `feat(streets): implement round completion detection and street progression`

---

## T3.6: 테이블별 동시성 락 + 액션 제출 API

**Goal**: 테이블별 in-memory 락과 액션 제출 API 엔드포인트를 구현한다.

**Deps**: T3.5, T3.4, T1.3

**Scope**:
- `app/core/table_lock.py`
- `app/api/private/action.py`

**AC**:
- [ ] 테이블별 `asyncio.Lock` 관리 (`Dict[int, asyncio.Lock]`)
- [ ] 같은 테이블의 액션은 반드시 직렬 처리. 다른 테이블은 병렬 가능
- [ ] `POST /v1/private/tables/{table_no}/action` 엔드포인트:
  ```json
  {
    "hand_id": 1,
    "state_version": 5,
    "idempotency_key": "uuid",
    "action": {"type": "RAISE_TO", "amount": 15}
  }
  ```
- [ ] `hand_id` 불일치 (현재 진행 중 핸드와 다름) → `409 STALE_STATE`
- [ ] `state_version` 불일치 → `409 STALE_STATE` (선택적 검증, 보내지 않으면 스킵)
- [ ] `idempotency_key` 중복 → 이전 결과 반환 (멱등성)
- [ ] 인증된 플레이어가 해당 테이블에 앉아 있지 않으면 → `403`
- [ ] 인증된 플레이어의 턴이 아니면 → `422 INVALID_ACTION`
- [ ] 액션 처리 성공 시 응답: 처리된 액션 정보 + 새 state_version
- [ ] 액션 처리 후 `table_snapshot` 갱신 (version 증가)
- [ ] DB 트랜잭션 내에서 모든 상태 변경 원자적 수행
- [ ] 단위 테스트:
  - 정상 액션 제출 → 성공
  - 턴 아닌 플레이어 → 에러
  - 잘못된 hand_id → 에러
  - 동시 요청 2개 → 하나만 성공 (또는 순차 처리)

**Commit**: `feat(action-api): add action submission endpoint with per-table locking`

---

# M4 — Showdown, Pots & Hand Completion

## T4.1: 사이드팟 계산기

**Goal**: 플레이어별 `hand_contribution`으로부터 메인팟/사이드팟을 계산하는 순수 함수를 구현한다.

**Deps**: T3.3

**Scope**:
- `app/core/pot_calculator.py`

**AC**:
- [ ] `calculate_pots(players: List[{seat_no, hand_contribution, folded}])` → `{main_pot, side_pots, uncalled_return}`
- [ ] **메인팟**: 모든 참가자가 매칭 가능한 최소 기여금 × 참가자 수
- [ ] **사이드팟**: 올인 금액 기준으로 계층적으로 분리. 각 사이드팟에 eligible_seats 포함
- [ ] **언콜 반환**: 마지막 베터의 초과 금액 (콜받지 못한 금액) 반환
- [ ] 폴드한 플레이어의 기여금은 팟에 포함되지만 eligible에서 제외
- [ ] **pot_view 형식** 반환:
  ```json
  {
    "main_pot": 120,
    "side_pots": [
      {"index": 1, "amount": 40, "eligible_seats": [2, 5]},
      {"index": 2, "amount": 18, "eligible_seats": [5, 7]}
    ],
    "uncalled_return": {"seat_no": 7, "amount": 5}
  }
  ```
- [ ] 단위 테스트 (최소 8개):
  - 2인 단순 (메인팟만)
  - 3인 전원 동일 기여 (메인팟만)
  - 3인, 1명 숏 올인 → 메인팟 + 사이드팟 1개
  - 3인, 2명 다른 금액 올인 → 메인팟 + 사이드팟 2개
  - 언콜 반환 케이스 (레이즈 후 전원 폴드)
  - 4인, 2명 폴드, 2명 쇼다운 → 폴드 기여금은 팟에 포함
  - 전원 올인 (3단계 사이드팟)
  - 총 팟 + 언콜 반환 = 총 기여금 (칩 보존 법칙 검증)

**Commit**: `feat(pots): implement side pot calculator from hand contributions`

---

## T4.2: 쇼다운 + 승자 결정 + 팟 분배

**Goal**: 쇼다운 로직, 승자 결정, 메인팟/사이드팟별 독립 분배를 구현한다.

**Deps**: T4.1, T3.1

**Scope**:
- `app/services/showdown_service.py`

**AC**:
- [ ] `resolve_showdown(hand)` → 각 팟별 승자 결정 + 칩 분배
- [ ] 각 팟(메인팟 + 각 사이드팟)에 대해 독립적으로:
  - eligible 플레이어들의 핸드 평가 (7장 = 홀카드 2장 + 보드 5장)
  - 최고 핸드를 가진 플레이어에게 해당 팟 지급
  - 동점 시 팟을 균등 분배 (정수 나눗셈)
  - **홀수 칩(odd chip)**: 버튼에서 시계 방향으로 가장 가까운 eligible seat에 지급
- [ ] 폴드 승리 (1명만 남음): 쇼다운 없이 남은 플레이어에게 전액 지급
- [ ] 언콜 금액 반환: 해당 플레이어 스택에 직접 반환
- [ ] 승자 플레이어의 `hand_players.ending_stack` 갱신, `table_seats.stack` 갱신
- [ ] 쇼다운 시 모든 생존 플레이어의 홀카드 공개 (머크 불가)
- [ ] `HandAction` 로그:
  - `SHOWDOWN` (is_system_action=true) — 각 플레이어의 공개 카드 + 핸드 랭크 포함
  - `POT_AWARDED` (is_system_action=true) — 각 팟의 수혜자 + 금액
- [ ] 단위 테스트:
  - 2인 쇼다운 → 승자 확인 + 스택 갱신
  - 동점 분배 (split pot)
  - 홀수 칩 분배
  - 사이드팟 있는 쇼다운 → 각 팟 독립 분배
  - 폴드 승리 → 카드 미공개, 전액 수령
  - 칩 보존 검증: 핸드 전 총 스택 == 핸드 후 총 스택

**Commit**: `feat(showdown): implement showdown resolution with pot distribution`

---

## T4.3: 핸드 완료 + 자동 다음 핸드

**Goal**: 핸드 종료 후 처리(결과 기록, 스택 0 이석, leave_after_hand 처리, 다음 핸드 자동 시작)를 구현한다.

**Deps**: T4.2, T3.5

**Scope**:
- `app/services/hand_service.py` (확장)
- `app/services/hand_completion.py`

**AC**:
- [ ] 핸드 종료 시 `hands.status = 'FINISHED'`, `hands.finished_at` 기록
- [ ] `HAND_FINISHED` 액션 로그 (is_system_action=true)
- [ ] `hand_results`에 결과 JSON 저장:
  - 승자(복수 가능), 각 팟 분배 내역, 보드, 공개된 홀카드, 핸드 랭크
- [ ] 각 `hand_players.ending_stack` 최종 확정
- [ ] **스택 0 플레이어 자동 이석**: 핸드 종료 후 스택 0인 플레이어 → 좌석 EMPTY, 스택 0이므로 `TABLE_CASHOUT`(delta=0) 기록
- [ ] **leave_after_hand 처리**: `LEAVING_AFTER_HAND` 상태 플레이어 → 스택→지갑 반환(`TABLE_CASHOUT` 원장) → 좌석 EMPTY
- [ ] **자동 다음 핸드**: 스택 > 0인 SEATED 플레이어가 2명 이상이면 짧은 대기(2초) 후 다음 핸드 자동 시작
  - 테이블 status가 OPEN일 때만. PAUSED/CLOSED면 시작하지 않음
- [ ] `table_snapshot` 갱신 (version 증가)
- [ ] 단위 테스트:
  - 핸드 종료 → status FINISHED, result 기록 확인
  - 스택 0 → 자동 이석 확인
  - leave_after_hand → 이석 + 칩 반환 확인
  - 2명 이상 남음 → 다음 핸드 시작 확인 (버튼 회전)
  - 1명만 남음 → 다음 핸드 미시작
  - PAUSED 테이블 → 다음 핸드 미시작

**Commit**: `feat(hand-complete): implement hand completion, auto-leave, and next hand trigger`

---

# M5 — Game State APIs & History

## T5.1: Private 게임 상태 API + 스냅샷

**Goal**: 플레이어 관점의 게임 상태 조회 API와 테이블 스냅샷 시스템을 구현한다.

**Deps**: T3.6, T4.3

**Scope**:
- `app/api/private/state.py`
- `app/services/snapshot_service.py`
- `app/schemas/game_state.py`

**AC**:
- [ ] `GET /v1/private/tables/{table_no}/state` → 플레이어 관점 상태 응답
- [ ] 응답 필드 (PROJECT.md §6.7 전체):
  - table_no, hand_id, street
  - 자기 홀카드 (2장 배열)
  - board (공개된 커뮤니티 카드)
  - seats: [{seat_no, nickname, stack, folded, all_in, round_contribution, hand_contribution}]
  - button_seat_no
  - action_seat_no (현재 액션 차례)
  - current_bet
  - to_call (자기가 콜해야 하는 금액)
  - legal_actions (자기가 가능한 액션 목록)
  - min_raise_to, max_raise_to
  - pot_view: {main_pot, side_pots, uncalled_return}
  - action_deadline_at (ISO 8601)
  - state_version
- [ ] 해당 테이블에 앉아 있지 않은 플레이어도 조회 가능 (단 홀카드는 빈 배열)
- [ ] **타인의 홀카드는 절대 미포함** (showdown 전)
- [ ] 핸드 미진행 시: hand_id=null, street=null, board=[], legal_actions=[]
- [ ] `table_snapshot` 테이블에 version(증가 정수) + snapshot_json 저장/갱신
- [ ] **Long-poll 지원**: `?since_version=123&wait_ms=25000`
  - `since_version` < 현재 version이면 즉시 응답
  - 같거나 크면 `wait_ms` 동안 대기 후 변경 없으면 304 또는 현재 상태 응답
  - 대기 중 변경 발생 시 즉시 응답
- [ ] 단위 테스트:
  - 착석 + 핸드 시작 → 자기 홀카드 포함 확인
  - 다른 플레이어 관점 → 타인 홀카드 미포함 확인
  - legal_actions 포함 확인
  - pot_view 포함 확인
  - 핸드 없을 때 → null 필드 확인

**Commit**: `feat(private-state): add private game state API with snapshot and long-poll`

---

## T5.2: Public 게임 상태 API

**Goal**: 관전자용 공개 게임 상태 조회 API를 구현한다.

**Deps**: T5.1

**Scope**:
- `app/api/public/game_state.py`

**AC**:
- [ ] `GET /v1/public/tables/{table_no}` 확장 — 핸드 진행 중일 때 게임 상태 포함:
  - table_no, status, hand_id, street
  - board
  - seats: [{seat_no, nickname, stack, folded, all_in}] — 홀카드 없음
  - button_seat_no, action_seat_no, current_bet
  - pot_view
  - action_deadline_at
  - state_version
- [ ] **모든 플레이어의 홀카드 미포함** (showdown 이전)
- [ ] 인증 불필요
- [ ] 존재하지 않는 table_no → `404`
- [ ] 단위 테스트:
  - 핸드 진행 중 조회 → 홀카드 없음 확인
  - pot_view 포함 확인
  - 핸드 없을 때 조회 → 좌석 정보만 확인

**Commit**: `feat(public-state): add public game state API without hole cards`

---

## T5.3: 핸드 이력 + 액션 이력 API

**Goal**: 완료된 핸드 이력과 액션 로그 조회 API를 구현한다.

**Deps**: T4.3

**Scope**:
- `app/api/public/history.py`
- `app/services/history_service.py`
- `app/schemas/history.py`

**AC**:
- [ ] `GET /v1/public/tables/{table_no}/hands` — 완료된 핸드 목록 (커서 페이지네이션)
  - 응답: hand_id, hand_no, started_at, finished_at, board, winners, pot_summary
- [ ] `GET /v1/public/tables/{table_no}/hands/{hand_id}` — 핸드 상세
  - 응답: 참가 플레이어, 보드, showdown 결과, 각 팟 분배, 최종 스택 변화
  - showdown 간 플레이어의 홀카드 포함. 폴드한 플레이어 홀카드는 비공개
- [ ] `GET /v1/public/tables/{table_no}/hands/{hand_id}/actions` — 핸드별 액션 로그
  - 응답: [{seq, street, actor_seat, actor_nickname, action_type, amount, amount_to, is_system_action, timestamp}]
- [ ] `GET /v1/public/tables/{table_no}/actions` — 테이블 전체 액션 로그 (커서 페이지네이션)
- [ ] **카드 공개 규칙**:
  - showdown까지 간 플레이어 홀카드 → 공개
  - showdown 없이 종료된 핸드의 폴드 플레이어 → 홀카드 비공개 (null 또는 미포함)
- [ ] 페이지네이션: `?limit=50&cursor={last_id}` → `{items, next_cursor, has_more}`
- [ ] `GET /v1/private/me/hands` — 자기가 참여한 핸드 목록 (인증 필요). 자기 홀카드 항상 포함
- [ ] 존재하지 않는 table_no 또는 hand_id → `404`
- [ ] 단위 테스트:
  - 핸드 완료 후 이력 조회 → 결과 확인
  - showdown 핸드 → 홀카드 공개 확인
  - 폴드 승리 핸드 → 폴드 플레이어 홀카드 비공개 확인
  - 페이지네이션 동작 확인
  - /me/hands → 자기 카드 포함 확인

**Commit**: `feat(history): add hand history and action log APIs with pagination`

---

# M6 — Background Tasks & Recovery

## T6.1: 자동 폴드 타임아웃 백그라운드 태스크

**Goal**: 10분(600초) 무응답 시 자동 FOLD를 수행하는 백그라운드 태스크를 구현한다.

**Deps**: T3.6

**Scope**:
- `app/tasks/timeout_checker.py`

**AC**:
- [ ] 서버 시작 시 백그라운드 태스크 등록 (FastAPI lifespan 또는 on_startup)
- [ ] 주기적(예: 5~10초 간격)으로 모든 진행 중 핸드의 `action_deadline_at` 체크
- [ ] `action_deadline_at < now()` 인 핸드 발견 시:
  - 해당 플레이어에 대해 자동 FOLD 처리
  - 액션 로그: `AUTO_FOLD_TIMEOUT` (is_system_action=true)
  - 체크 가능한 상황이라도 예외 없이 FOLD
- [ ] 자동 폴드 후 정상 게임 진행 (다음 액터 이동, 라운드 종료 판단 등)
- [ ] 테이블별 락을 획득한 후 처리 (동시성 안전)
- [ ] ±수초 오차 허용
- [ ] 단위 테스트:
  - 액션 데드라인 경과 → 자동 폴드 발생 확인
  - 자동 폴드 후 게임 진행 확인
  - 로그에 AUTO_FOLD_TIMEOUT 기록 확인
  - 데드라인 미경과 → 폴드 미발생

**Commit**: `feat(timeout): add auto-fold timeout background task`

---

## T6.2: Nonce 정리 + 서버 재시작 복구

**Goal**: 만료 nonce 정리 태스크와 서버 재시작 시 진행 중 핸드 복구 로직을 구현한다.

**Deps**: T4.3, T6.1

**Scope**:
- `app/tasks/nonce_cleanup.py`
- `app/services/recovery_service.py`

**AC**:
- [ ] **Nonce 정리**:
  - 주기적(예: 5분 간격) 백그라운드 태스크
  - `api_nonces` 테이블에서 timestamp + 600초(10분) 이전 레코드 삭제
  - 삭제 건수 로그 출력
- [ ] **서버 재시작 복구**:
  - 서버 시작 시 (lifespan/on_startup) DB에서 `hands.status = 'IN_PROGRESS'` 조회
  - 각 진행 중 핸드에 대해:
    - 해당 테이블의 in-memory 락 초기화
    - 핸드 상태를 메모리에 로드 (deck, board, players, contributions 등)
    - `action_deadline_at` 재계산 (서버 다운 시간 동안 경과했을 수 있음)
    - 타임아웃 체커가 즉시 해당 핸드를 감지할 수 있도록 설정
  - 복구 완료 후 정상 운영 가능
- [ ] 복구 시 DB의 핸드 데이터(`deck_json`, `deal_index`, `board_json`, `hand_players`, `hand_actions`)만으로 상태 재구성 가능
- [ ] 단위 테스트:
  - nonce 삽입 → 시간 경과 시뮬레이션 → cleanup 후 삭제 확인
  - 핸드 진행 중 상태에서 서버 재시작 → 핸드 계속 진행 가능

**Commit**: `feat(recovery): add nonce cleanup task and server restart recovery`

---

# M7 — Admin UI & Deployment

## T7.1: 관리자 웹 UI — 계정/키/칩 관리

**Goal**: 관리자용 웹 인터페이스의 계정, API 키, 칩 관리 페이지를 구현한다.

**Deps**: T1.5.1, T1.2

**Scope**:
- `app/api/admin/views.py` (HTML 렌더링)
- `app/templates/admin/` (Jinja2 템플릿)
- `app/static/` (최소 CSS)

**AC**:
- [ ] `/admin/login` — 비밀번호 입력 폼 → 세션 쿠키 발급
- [ ] `/admin/` — 대시보드 (계정 수, 테이블 수, 총 칩 발행량 요약)
- [ ] `/admin/accounts` — 계정 목록 페이지
  - 테이블: nickname, status, wallet_balance, created_at
  - "계정 생성" 버튼 → 닉네임 입력 폼
  - 각 계정에 "상세 보기" 링크
- [ ] `/admin/accounts/{id}` — 계정 상세 페이지
  - 계정 정보, 현재 착석 테이블
  - API 키 상태 (api_key 마스킹, status)
  - "키 발급" 버튼 → 생성 후 SECRET_KEY 1회 표시 (복사 가능)
  - "키 폐기" 버튼
  - 칩 지급/차감 폼 (금액 + 사유)
  - 칩 원장 이력 테이블
- [ ] 관리자 세션이 없으면 `/admin/login`으로 리다이렉트
- [ ] Jinja2 템플릿 기반 서버 렌더링
- [ ] 기능 테스트: 로그인 → 계정 생성 → 키 발급 → 칩 지급 → 원장 확인 (수동 또는 E2E)

**Commit**: `feat(admin-ui): add admin web UI for accounts, credentials, and chips`

---

## T7.2: 관리자 웹 UI — 테이블/게임 관리

**Goal**: 관리자 웹 인터페이스의 테이블 관리, 게임 상태 조회, 이력 조회 페이지를 구현한다.

**Deps**: T7.1, T5.3

**Scope**:
- `app/templates/admin/` (추가 템플릿)
- `app/api/admin/views.py` (확장)

**AC**:
- [ ] `/admin/tables` — 테이블 목록 페이지
  - 테이블: table_no, status, 착석 인원/총좌석, 현재 핸드 유무
  - "테이블 생성" 버튼 → table_no 입력 폼
  - 각 테이블에 일시정지/재개/종료 버튼 (현재 상태에 따라 활성/비활성)
- [ ] `/admin/tables/{table_no}` — 테이블 상세 페이지
  - 좌석 현황: 각 좌석의 플레이어, 스택, 상태
  - 현재 핸드 정보 (진행 중이면): street, board, pot, 각 플레이어 홀카드(관리자는 볼 수 있음)
  - 완료된 핸드 이력 목록 (최근 20개)
- [ ] `/admin/tables/{table_no}/hands/{hand_id}` — 핸드 상세 페이지
  - 참가 플레이어 목록 (홀카드 포함 — 관리자 전용)
  - 보드 카드
  - 액션 로그 전체 (시간순)
  - 결과: 승자, 팟 분배 내역
- [ ] 관리자 화면에서는 **진행 중 핸드의 모든 플레이어 홀카드** 조회 가능 (디버그 용도)
- [ ] 기능 테스트: 테이블 생성 → 상태 전이 → 핸드 이력 조회 (수동)

**Commit**: `feat(admin-ui): add admin web UI for table management and game history`

---

## T7.3: Dockerfile + Railway 배포 설정

**Goal**: Railway에 배포 가능한 Dockerfile과 설정 파일을 구성한다.

**Deps**: 전체 기능 구현 완료

**Scope**:
- `Dockerfile`
- `railway.toml` 또는 `railway.json` (있으면)
- `README.md`

**AC**:
- [ ] `Dockerfile`:
  - Python 3.12 기반
  - 의존성 설치
  - Alembic 마이그레이션 실행 (`alembic upgrade head`)
  - Uvicorn으로 서버 기동 (`PORT` 환경변수 사용)
- [ ] `docker build . && docker run -p 8000:8000 --env-file .env app` 으로 로컬 실행 가능
- [ ] Railway 배포에 필요한 설정:
  - `PORT` 환경변수로 포트 바인딩
  - `DATABASE_URL` 환경변수로 PostgreSQL 연결
  - 헬스 체크 경로: `/health`
- [ ] `README.md` 포함 내용:
  - 프로젝트 설명 (1~2줄)
  - 로컬 개발 환경 설정 방법 (docker-compose, venv, alembic)
  - 환경변수 목록 (.env.example 참조)
  - API 사용법 요약 (인증 방식, 주요 엔드포인트)
  - Railway 배포 방법
  - 테스트 실행 방법
- [ ] `docker compose up` 후 전체 기능 정상 동작 확인

**Commit**: `feat(deploy): add Dockerfile, Railway config, and README`

---

## T7.4: 통합 / 시나리오 테스트

**Goal**: 전체 게임 플로우를 검증하는 통합 테스트를 작성한다.

**Deps**: 전체 기능 구현 완료

**Scope**:
- `tests/integration/`
- `tests/scenarios/`

**AC**:
- [ ] **시나리오 1: 2인 전체 플로우**
  - 계정 2개 생성 → 키 발급 → 칩 지급 → 테이블 생성 → 착석 → 핸드 자동 시작
  - 프리플랍 액션 → 플랍 → 턴 → 리버 → 쇼다운 → 팟 분배
  - 칩 보존 검증 (핸드 전 총합 == 핸드 후 총합)
- [ ] **시나리오 2: 3인 다중 올인**
  - 3명, 각각 다른 스택으로 시작
  - 전원 올인 → 사이드팟 생성 → 보드 즉시 딜 → 쇼다운
  - 메인팟/사이드팟 정확 분배 검증
- [ ] **시나리오 3: 타임아웃 자동 폴드**
  - 플레이어 턴에서 10분 경과 → AUTO_FOLD_TIMEOUT 발생 확인
  - 게임 정상 진행 확인
- [ ] **시나리오 4: 핸드 중 이석**
  - 핸드 중 이석 요청 → LEAVING_AFTER_HAND
  - 핸드 종료 후 이석 + 칩 반환 확인
- [ ] **시나리오 5: 멀티테이블 동시 진행**
  - 테이블 2개에서 동시에 핸드 진행
  - 각 테이블 독립 동작 확인
- [ ] **회귀 테스트**:
  - 총 칩 보존 검증 (모든 시나리오)
  - 액션 로그 seq 순서 검증
  - 공개 API에서 비공개 카드 미노출 검증
- [ ] 모든 테스트가 `pytest` 로 실행 가능
- [ ] CI 환경에서도 실행 가능 (docker-compose 기반 DB)

**Commit**: `test(integration): add full game flow integration and scenario tests`

---

# M8 — AI Bot Players

## 개요

사람 플레이어들이 연습할 수 있도록 **3종류의 AI 봇**을 구현한다.

### 봇 타입

| 타입 | 약칭 | 성격 | 프리플롭 레인지 | 특징 |
|------|------|------|----------------|------|
| **Tight-Aggressive (TAG)** | `TAG` | 좁고 공격적 | ~15% | 프리미엄 핸드만 플레이, 들어가면 강하게 베팅/레이즈. 블러프 빈도 낮음 (~5%). 솔리드한 정석 플레이어 |
| **Loose-Aggressive (LAG)** | `LAG` | 넓고 공격적 | ~40% | 많은 핸드를 공격적으로 플레이. 세미블러프, 컨티뉴에이션 벳 빈번. 블러프 빈도 높음 (~25%). 상대에게 압박을 줌 |
| **Calling Station** | `FISH` | 넓고 수동적 | ~55% | 많은 핸드를 콜 위주로 플레이. 잘 폴드 안 함, 잘 레이즈 안 함. 초보자가 밸류 베팅을 연습하기 좋은 상대 |

### 초기 구성

- 테이블 2개 (table_no: 1, 2)
- 각 테이블에 3종류 봇 1개씩 착석 (총 6개 봇)
- 봇 닉네임: `bot_tag_1`, `bot_tag_2`, `bot_lag_1`, `bot_lag_2`, `bot_fish_1`, `bot_fish_2`

### 아키텍처 결정

- 봇은 **동일 FastAPI 앱 내 백그라운드 태스크**로 실행 (별도 서비스 X)
- 봇은 내부 서비스 함수(`action_service.process_action`)를 직접 호출 (HMAC 오버헤드 없음)
- 봇 계정은 기존 `Account` 모델에 `is_bot` 플래그 추가
- 봇 프로필은 별도 `BotProfile` 모델로 관리
- 관리자가 Admin API/UI를 통해 봇을 착석/이석 가능
- Railway 단일 서비스로 배포 (추가 서비스 불필요)

---

## T8.1: Bot 데이터 모델 & Alembic 마이그레이션

**Goal**: 봇 관련 DB 모델을 정의하고 마이그레이션을 생성한다.

**Deps**: T0.2

**Scope**:
- `app/models/account.py` 수정 — `is_bot` 필드 추가
- `app/models/bot.py` 신규 — `BotProfile` 모델
- `app/bots/__init__.py` 신규 — `BotType` enum
- `app/config.py` 수정 — 봇 관련 설정 추가
- Alembic 마이그레이션

**AC**:
- [ ] `Account` 모델에 `is_bot: bool = False` 컬럼 추가
- [ ] `BotProfile` 모델 정의:
  - `id` (int, PK)
  - `account_id` (FK → Account, unique) — 1:1 관계
  - `bot_type` (str) — `TAG`, `LAG`, `FISH`
  - `display_name` (str) — 봇 표시 이름
  - `is_active` (bool, default True) — 봇 활성화 여부
  - `config_json` (JSON, nullable) — 봇 커스텀 설정 (향후 확장용)
  - `created_at`, `updated_at` (datetime)
- [ ] `BotType` enum 정의: `TAG`, `LAG`, `FISH`
- [ ] `app/config.py`에 다음 설정 추가:
  - `BOT_ENABLED: bool = True` — 봇 러너 활성화 여부
  - `BOT_POLL_INTERVAL: float = 2.0` — 봇 턴 폴링 주기(초)
  - `BOT_ACTION_DELAY_MIN: float = 1.0` — 봇 액션 전 최소 대기(초)
  - `BOT_ACTION_DELAY_MAX: float = 3.0` — 봇 액션 전 최대 대기(초)
  - `BOT_AUTO_SEED: bool = False` — 서버 시작 시 봇 자동 생성 여부
  - `BOT_INITIAL_CHIPS: int = 1000` — 봇 자동 생성 시 지급 칩
- [ ] Alembic 마이그레이션 생성 및 적용 가능
- [ ] `BotProfile.bot_type`에 대해 CHECK 제약 또는 Enum 타입 적용
- [ ] 기존 테스트 깨지지 않음

**Commit**: `feat(bot-model): add BotProfile model, Account.is_bot flag, and bot config settings`

---

## T8.2: Bot 전략 엔진 — 프리플롭 핸드 레인지

**Goal**: 프리플롭에서 봇이 핸드를 플레이할지, 어떤 액션을 취할지 결정하는 핸드 레인지 시스템을 구현한다.

**Deps**: T8.1, T3.1

**Scope**:
- `app/bots/hand_range.py` — 핸드 분류 + 레인지 테이블
- `app/bots/preflop.py` — 프리플롭 의사결정 로직
- `tests/test_t8_2_preflop.py`

**AC**:
- [ ] 핸드 분류 함수 구현:
  - `classify_hole_cards(card1: str, card2: str) -> str` — `"AA"`, `"AKs"`, `"AKo"`, `"T9s"` 등 표준 표기 반환
  - Pair(e.g., `AA`, `KK`), Suited(e.g., `AKs`), Offsuit(e.g., `AKo`) 구분
- [ ] 3종류 레인지 테이블 정의:
  - **TAG**: ~15% — `AA-88`, `AKs-ATs`, `KQs`, `AKo-AJo` 등 프리미엄 핸드만
  - **LAG**: ~40% — TAG 레인지 + `77-22`, `A9s-A2s`, `KJs-K9s`, `QJs-Q9s`, `JTs-76s`, `ATo-A8o`, `KQo-KTo` 등
  - **FISH**: ~55% — LAG 레인지 + `65s-54s`, `K8s-K2s`, `Q8s-Q2s`, `A7o-A2o`, `KJo-K9o`, `QJo-Q9o`, `J9o-T8o` 등
- [ ] `PreflopDecision` 반환 타입 정의:
  - `action_type`: `FOLD`, `CHECK`, `CALL`, `RAISE_TO`, `ALL_IN`
  - `amount`: 레이즈 시 금액 (없으면 None)
- [ ] 프리플롭 의사결정 함수:
  - `decide_preflop(bot_type: BotType, hole_cards: list[str], legal_actions: list[dict], current_bet: int, stack: int, pot_size: int) -> PreflopDecision`
  - 레인지 밖 핸드 → FOLD (단, FISH는 일정 확률로 콜)
  - 레인지 안 핸드:
    - TAG: 레이즈 위주 (70% raise, 30% call)
    - LAG: 레이즈 위주 (80% raise, 15% call, 5% all-in bluff)
    - FISH: 콜 위주 (20% raise, 75% call, 5% check)
  - `random` 기반 확률적 선택으로 예측 불가능성 부여
  - 레이즈 금액: TAG/LAG는 2.5~3.5x BB 범위, FISH는 min-raise
- [ ] 유닛 테스트:
  - 각 봇 타입별로 AA가 레인지에 포함됨
  - TAG는 72o를 폴드함
  - FISH는 넓은 레인지를 가짐
  - 반환 액션이 항상 legal_actions 범위 내임
  - `pytest tests/test_t8_2_preflop.py` 통과

**Commit**: `feat(bot-preflop): add preflop hand range tables and decision logic for 3 bot types`

---

## T8.3: Bot 전략 엔진 — 포스트플롭 의사결정

**Goal**: 플롭/턴/리버에서 봇이 핸드 강도와 팟 오즈를 기반으로 액션을 결정하는 로직을 구현한다.

**Deps**: T8.2, T3.1

**Scope**:
- `app/bots/postflop.py` — 포스트플롭 의사결정 로직
- `app/bots/hand_strength.py` — 핸드 강도 평가 래퍼
- `app/bots/strategy.py` — 통합 전략 인터페이스 (프리플롭 + 포스트플롭)
- `tests/test_t8_3_postflop.py`

**AC**:
- [ ] `evaluate_hand_strength(hole_cards: list[str], board: list[str]) -> float` 구현:
  - 기존 `evaluator.py`의 `best_hand()` 활용
  - 핸드 랭크(0~9)를 0.0~1.0 정규화 점수로 변환
  - 보드 카드 수에 따라 가중치 조정 (플롭: 불확실성 높음, 리버: 확정)
- [ ] `calculate_pot_odds(to_call: int, pot_size: int) -> float` 구현:
  - `to_call / (pot_size + to_call)` — 콜에 필요한 팟 오즈
- [ ] 포스트플롭 의사결정 함수:
  - `decide_postflop(bot_type: BotType, hole_cards: list[str], board: list[str], legal_actions: list[dict], current_bet: int, to_call: int, stack: int, pot_size: int) -> PostflopDecision`
  - 핸드 강도 vs 팟 오즈 비교로 기본 판단
  - 봇 타입별 성격 반영:
    - **TAG**:
      - 강한 핸드(≥0.7) → 베팅/레이즈 (팟의 60~80%)
      - 중간 핸드(0.4~0.7) → 체크/콜
      - 약한 핸드(<0.4) → 체크/폴드
      - 블러프 빈도: ~5%
    - **LAG**:
      - 강한 핸드(≥0.6) → 공격적 베팅/레이즈 (팟의 70~100%)
      - 중간 핸드(0.3~0.6) → 세미블러프 or 콜 (50/50)
      - 약한 핸드(<0.3) → 블러프 or 폴드
      - 블러프 빈도: ~25%
    - **FISH**:
      - 핸드 강도와 무관하게 콜 위주
      - 강한 핸드(≥0.7) → 콜/체크 (80%), 레이즈 (20%)
      - 중간 핸드(0.3~0.7) → 콜 (70%), 체크 (20%), 폴드 (10%)
      - 약한 핸드(<0.3) → 콜 (40%), 체크 (30%), 폴드 (30%)
  - 베팅/레이즈 금액: 팟 비율 기반 + 봇 타입별 분산
- [ ] 통합 전략 인터페이스:
  - `decide(bot_type, street, hole_cards, board, legal_actions, current_bet, to_call, stack, pot_size) -> BotDecision`
  - `street == "preflop"` → `decide_preflop()` 호출
  - 그 외 → `decide_postflop()` 호출
  - 최종 반환값이 legal_actions 범위 내인지 검증 (아니면 폴백: FOLD or CHECK)
- [ ] 유닛 테스트:
  - 핸드 강도 평가가 0.0~1.0 범위 반환
  - TAG가 강한 핸드로 베팅하는지 확인
  - FISH가 약한 핸드에도 콜하는지 확인
  - 반환 액션이 항상 유효한 legal action인지 확인
  - `pytest tests/test_t8_3_postflop.py` 통과

**Commit**: `feat(bot-postflop): add postflop decision engine with hand strength and pot odds`

---

## T8.4: Bot 러너 백그라운드 태스크

**Goal**: 봇의 턴을 감지하고 자동으로 액션을 제출하는 백그라운드 루프를 구현한다.

**Deps**: T8.3, T3.6, T4.3

**Scope**:
- `app/bots/runner.py` — 봇 러너 백그라운드 태스크
- `app/main.py` 수정 — lifespan에 봇 러너 등록
- `tests/test_t8_4_runner.py`

**AC**:
- [ ] `bot_runner_loop()` 구현:
  - `BOT_ENABLED`이 `False`면 즉시 리턴
  - `BOT_POLL_INTERVAL` 간격으로 폴링
  - 매 루프마다:
    1. 모든 활성 봇 프로필 조회 (`is_active=True`)
    2. 각 봇의 현재 착석 상태 확인 (TableSeat에서 account_id로 조회)
    3. 착석 중인 봇에 대해, IN_PROGRESS 핸드의 `action_seat_no`가 봇의 시트인지 확인
    4. 봇의 턴이면:
       - 게임 상태 로드 (핸드, 홀카드, 보드, legal_actions, pot 등)
       - `random.uniform(BOT_ACTION_DELAY_MIN, BOT_ACTION_DELAY_MAX)` 만큼 대기
       - 전략 엔진 호출 (`strategy.decide()`)
       - per-table lock 획득 후 `action_service.process_action()` 호출
       - 액션 결과 로깅
  - 에러 발생 시 해당 봇만 스킵하고 루프 계속 (전체 중단 X)
  - 각 루프 에러는 `logging.exception()`으로 기록
- [ ] `app/main.py` lifespan에 봇 러너 태스크 추가:
  - `bot_task = asyncio.ensure_future(bot_runner_loop())`
  - shutdown 시 cancel
- [ ] 봇 액션 로그에 `is_system_action = False` 유지 (봇은 플레이어처럼 기록)
- [ ] 팟 사이즈 계산: `HandPlayer` 전체의 `hand_contribution` 합산
- [ ] 봇이 쇼다운 이후 상태의 핸드에는 액션하지 않음
- [ ] 테스트:
  - 봇 턴 감지 로직 유닛 테스트
  - 봇이 유효한 액션을 제출하는지 확인
  - `pytest tests/test_t8_4_runner.py` 통과

**Commit**: `feat(bot-runner): add background task for automated bot action submission`

---

## T8.5: Admin Bot 관리 API

**Goal**: 관리자가 봇을 생성, 조회, 착석/이석할 수 있는 API를 구현한다.

**Deps**: T8.1, T2.2

**Scope**:
- `app/api/admin/bots.py` — 봇 관리 API 라우터
- `app/services/bot_service.py` — 봇 비즈니스 로직
- `app/schemas/bot.py` — 요청/응답 스키마
- `app/main.py` 수정 — 라우터 등록
- `tests/test_t8_5_bot_api.py`

**AC**:
- [ ] `POST /admin/bots` — 봇 생성:
  - Request: `{ "bot_type": "TAG"|"LAG"|"FISH", "display_name": "bot_tag_1" }`
  - 내부 처리:
    1. Account 생성 (`nickname=display_name`, `is_bot=True`)
    2. BotProfile 생성 (`bot_type`, `display_name`, `is_active=True`)
    3. 칩 지급 (`BOT_INITIAL_CHIPS` 만큼, reason: `ADMIN_GRANT`)
  - Response: `{ "bot_id": 1, "account_id": 1, "bot_type": "TAG", "display_name": "bot_tag_1", "chips": 1000 }`
  - 동일 `display_name` 중복 시 409
- [ ] `GET /admin/bots` — 봇 목록:
  - Response: 봇 프로필 + 현재 착석 정보 (table_no, seat_no, stack) + 지갑 잔액
  - `is_active` 필터 파라미터 (기본: 전체)
- [ ] `POST /admin/bots/{bot_id}/seat` — 봇 착석:
  - Request: `{ "table_no": 1, "seat_no": 3 }` (seat_no 선택적)
  - 기존 `seat_service.sit()` 재사용 (account_id로 호출)
  - 봇 프로필이 존재하지 않거나 비활성이면 404
  - 이미 착석 중이면 409
- [ ] `POST /admin/bots/{bot_id}/unseat` — 봇 이석:
  - 현재 착석 중인 테이블에서 이석
  - 기존 `seat_service.stand()` 재사용
  - 착석 중이 아니면 404
- [ ] `DELETE /admin/bots/{bot_id}` — 봇 비활성화:
  - `is_active = False`로 변경
  - 착석 중이면 먼저 이석 처리
  - Account의 `status`는 변경하지 않음 (칩 보존)
- [ ] 모든 엔드포인트에 Admin 인증 적용
- [ ] Pydantic 스키마:
  - `BotCreate`, `BotResponse`, `BotListItem`, `BotSeatRequest`
- [ ] 테스트:
  - 봇 생성 → 목록 조회 → 착석 → 이석 플로우
  - 중복 생성 409 확인
  - 미착석 상태에서 이석 404 확인
  - `pytest tests/test_t8_5_bot_api.py` 통과

**Commit**: `feat(bot-api): add admin API for bot creation, listing, seating, and removal`

---

## T8.6: Admin UI — Bot 관리 페이지

**Goal**: 관리자 웹 UI에 봇 관리 페이지를 추가한다.

**Deps**: T8.5, T7.1

**Scope**:
- `app/templates/admin/bots.html` — 봇 관리 페이지
- `app/api/admin/views.py` 수정 — 봇 관리 뷰 라우트 추가
- `app/templates/admin/dashboard.html` 수정 — 대시보드에 봇 요약 추가

**AC**:
- [ ] `/admin/bots` 페이지:
  - 봇 목록 테이블: 이름, 타입, 상태(활성/비활성), 현재 테이블, 좌석, 스택, 지갑 잔액
  - 봇 타입별 아이콘/색상 구분 (TAG: 파란색, LAG: 빨간색, FISH: 초록색)
  - **봇 생성 폼**: 타입 선택(드롭다운), 이름 입력
  - **착석 버튼**: 테이블 번호 + 좌석 번호(선택) 입력 모달
  - **이석 버튼**: 확인 후 이석
  - **비활성화 버튼**: 확인 후 비활성화
- [ ] 대시보드(`/admin/`)에 봇 요약 정보 추가:
  - 활성 봇 수
  - 현재 착석 중인 봇 수
  - 봇 관리 페이지 링크
- [ ] 네비게이션에 "Bots" 메뉴 항목 추가
- [ ] 기존 Admin UI 스타일과 일관된 디자인
- [ ] JavaScript fetch로 봇 API 호출 (기존 Admin UI 패턴 따름)

**Commit**: `feat(bot-ui): add admin web UI for bot management and dashboard integration`

---

## T8.7: Bot 초기화 시드 & 자동 착석

**Goal**: 서버 시작 시 봇 계정을 자동으로 생성하고, 지정된 테이블에 착석시키는 시드 로직을 구현한다.

**Deps**: T8.5, T8.4

**Scope**:
- `app/bots/seed.py` — 봇 시드 로직
- `app/main.py` 수정 — lifespan에 시드 호출 추가
- `app/config.py` 수정 — 시드 관련 설정 추가

**AC**:
- [ ] `seed_bots(session)` 함수 구현:
  - 이미 존재하는 봇은 스킵 (닉네임 기준 중복 체크)
  - 6개 봇 계정 자동 생성:
    | 닉네임 | 타입 | 초기 테이블 |
    |--------|------|------------|
    | `bot_tag_1` | TAG | 1 |
    | `bot_lag_1` | LAG | 1 |
    | `bot_fish_1` | FISH | 1 |
    | `bot_tag_2` | TAG | 2 |
    | `bot_lag_2` | LAG | 2 |
    | `bot_fish_2` | FISH | 2 |
  - 각 봇에 `BOT_INITIAL_CHIPS` 만큼 칩 지급
  - 테이블 1, 2 자동 생성 (없으면)
  - 각 봇을 지정 테이블에 자동 착석
- [ ] `BOT_AUTO_SEED = True`일 때만 시드 실행
- [ ] lifespan 순서: recovery → seed_bots → bot_runner_loop
- [ ] 시드 실행 시 로깅:
  - 생성된 봇 목록
  - 스킵된 봇 (이미 존재)
  - 착석 결과
- [ ] 시드 실패 시 (예: DB 에러) 서버 기동은 계속되어야 함 (fail-open)
- [ ] 이미 착석 중인 봇은 재착석 시도하지 않음
- [ ] `.env.example` 업데이트:
  - `BOT_ENABLED`, `BOT_AUTO_SEED`, `BOT_INITIAL_CHIPS`, `BOT_POLL_INTERVAL`, `BOT_ACTION_DELAY_MIN`, `BOT_ACTION_DELAY_MAX` 추가

**Commit**: `feat(bot-seed): add automatic bot creation and table seating on server startup`

---

## T8.8: Bot 통합 테스트

**Goal**: 봇이 실제 게임에서 올바르게 동작하는지 검증하는 통합 테스트를 작성한다.

**Deps**: T8.4, T8.5, T8.7

**Scope**:
- `tests/test_t8_8_bot_integration.py`

**AC**:
- [ ] **테스트 1: 봇 생성 & 관리 플로우**
  - 봇 3개 생성 (각 타입 1개) → 목록 조회 → 착석 → 이석
  - API 응답 검증
- [ ] **테스트 2: 봇끼리 핸드 완주**
  - 테이블에 봇 3개 착석
  - 핸드 시작 → 봇 전략 엔진으로 프리플롭~쇼다운까지 진행
  - 핸드 정상 완료 (status = FINISHED) 확인
  - 칩 보존 검증 (핸드 전 총합 == 핸드 후 총합)
- [ ] **테스트 3: 각 봇 타입별 액션 유효성**
  - 봇이 제출하는 모든 액션이 legal_actions 범위 내인지 확인
  - TAG가 72o를 폴드하는 경향 확인 (다수 반복으로 통계적 검증)
  - FISH가 콜 빈도 높은지 확인
- [ ] **테스트 4: 봇 + 사람 혼합 테이블**
  - 봇 2 + 사람 계정 1의 혼합 테이블
  - 사람이 액션 제출 → 봇이 자동 응답하는 플로우 검증
- [ ] **테스트 5: 멀티 핸드 연속 진행**
  - 봇 3개로 5핸드 연속 진행
  - 모든 핸드가 정상 완료되는지 확인
  - 스택 0인 봇이 자동 이석 처리되는지 확인
- [ ] 모든 테스트가 `pytest tests/test_t8_8_bot_integration.py` 로 실행 가능

**Commit**: `test(bot): add integration tests for bot gameplay, strategy, and management`

---

# M9 — Spectator UI & Leaderboard

## 개요

참가자와 관전자가 **브라우저에서 게임을 관전**하고, **순위와 히스토리를 조회**할 수 있는 공개 뷰어 UI를 구현한다.

인증 불필요. 기존 Public API(`/v1/public/*`)를 프론트엔드에서 호출하여 데이터를 표시한다.

### 페이지 구성

| 경로 | 페이지 | 설명 |
|------|--------|------|
| `/viewer/` | 로비 | 테이블 목록 카드, 착석 현황, 리더보드 상위 5명 |
| `/viewer/tables/{no}` | 라이브 테이블 뷰 | 실시간 게임 상태, 좌석 배치, 보드카드, 팟, 액션 피드 (JS 폴링 자동갱신) |
| `/viewer/leaderboard` | 리더보드 | 전체 플레이어 순위표 (총 칩, 핸드 수, 승률, 최대 팟) |
| `/viewer/tables/{no}/hands` | 핸드 히스토리 목록 | 테이블별 완료된 핸드 목록 (페이지네이션) |
| `/viewer/tables/{no}/hands/{id}` | 핸드 상세 | 핸드 리플레이 — 스트리트별 액션 타임라인, 보드 진행, 팟 분배 결과 |

### 기술 방향

- 서버 렌더링(Jinja2) + JavaScript(fetch 폴링)
- 별도 `templates/viewer/` 디렉터리 (Admin UI와 분리)
- 공개 API 엔드포인트 활용 + 리더보드용 통계 API 신규 추가
- 모바일 반응형 (참가자가 핸드폰으로 관전 가능)
- Admin UI와 독립된 스타일시트 (`viewer.css`)

---

## T9.1: 리더보드 통계 API

**Goal**: 플레이어 순위를 산출하는 통계 집계 API를 구현한다.

**Deps**: T5.3

**Scope**:
- `app/services/leaderboard_service.py` — 통계 집계 로직
- `app/api/public/leaderboard.py` — 공개 API 엔드포인트
- `app/schemas/leaderboard.py` — 응답 스키마
- `app/main.py` 수정 — 라우터 등록
- `tests/test_t9_1_leaderboard.py`

**AC**:
- [ ] `GET /v1/public/leaderboard` 엔드포인트:
  - 쿼리 파라미터: `sort_by` (`chips` | `profit` | `win_rate` | `hands_played`, 기본 `chips`), `limit` (기본 50)
  - Response:
    ```json
    {
      "items": [
        {
          "rank": 1,
          "nickname": "player1",
          "is_bot": false,
          "total_chips": 520,
          "wallet_balance": 480,
          "table_stack": 40,
          "hands_played": 25,
          "hands_won": 12,
          "win_rate": 0.48,
          "total_profit": 120,
          "biggest_pot_won": 86,
          "current_table": 1
        }
      ],
      "updated_at": "2026-03-21T12:00:00Z"
    }
    ```
- [ ] 통계 집계 로직:
  - `total_chips` = `wallet_balance` + 현재 착석 중인 테이블의 `stack` (있으면)
  - `hands_played` = `HandPlayer` 레코드 수 (FINISHED 핸드만)
  - `hands_won` = 핸드 결과에서 `awards`에 해당 좌석이 포함된 핸드 수
  - `win_rate` = `hands_won / hands_played` (핸드 0이면 0.0)
  - `total_profit` = `총 칩 - 최초 지급 칩` (ChipLedger의 ADMIN_GRANT 합산 대비 현재 보유량)
  - `biggest_pot_won` = 단일 핸드에서 가장 많이 획득한 칩 (ending_stack - starting_stack 최대)
  - `current_table` = 현재 착석 중인 테이블 번호 (없으면 null)
- [ ] `is_bot` 필드 포함 (Account.is_bot) — 봇과 사람 구분
- [ ] 봇 포함/제외 필터: `include_bots` 쿼리 파라미터 (기본 true)
- [ ] 테스트:
  - 2명 이상 플레이어로 핸드 진행 후 리더보드 조회
  - 정렬 기준별 순서 검증
  - 봇 필터 동작 확인
  - `pytest tests/test_t9_1_leaderboard.py` 통과

**Commit**: `feat(leaderboard): add player statistics aggregation and public leaderboard API`

---

## T9.2: Viewer 기본 레이아웃 & 로비 페이지

**Goal**: 관전자용 기본 레이아웃(base template, CSS)과 로비 페이지를 구현한다.

**Deps**: T9.1, T5.2

**Scope**:
- `app/templates/viewer/base.html` — 관전자 UI 기본 레이아웃
- `app/templates/viewer/lobby.html` — 로비 페이지
- `app/static/viewer.css` — 관전자 UI 스타일시트
- `app/api/viewer/views.py` — 관전자 뷰 라우트
- `app/main.py` 수정 — 라우터 등록

**AC**:
- [ ] 기본 레이아웃 (`base.html`):
  - 네비게이션: 로비, 리더보드 링크
  - 프로젝트 로고/타이틀 "Pokerthon"
  - 반응형 디자인 (모바일 768px 이하 대응)
  - 다크 테마 (포커 분위기)
- [ ] 로비 페이지 (`/viewer/`):
  - **테이블 카드 그리드**: 각 테이블을 카드 형태로 표시
    - 테이블 번호, 상태 (OPEN/PAUSED/CLOSED 뱃지)
    - 착석 현황 (`3/9` 형태)
    - 현재 핸드 진행 여부 (라이브 뱃지)
    - 블라인드 정보 (1/2)
    - "관전하기" 링크 → `/viewer/tables/{no}`
  - **리더보드 요약**: 상위 5명 미니 테이블
    - 순위, 닉네임, 총 칩
    - "전체 보기" 링크 → `/viewer/leaderboard`
  - JavaScript: 30초마다 자동 새로고침 (fetch `/v1/public/tables` + `/v1/public/leaderboard`)
- [ ] `viewer.css`:
  - 다크 그린 배경 (#1a3a1a 또는 유사), 포커 테이블 느낌
  - 카드 컴포넌트, 뱃지, 테이블 스타일
  - 반응형 그리드 (PC 3열, 태블릿 2열, 모바일 1열)
- [ ] `/viewer/` 경로에 인증 없이 접근 가능
- [ ] Admin UI와 완전 독립 (별도 base.html, 별도 CSS)

**Commit**: `feat(viewer): add spectator base layout, lobby page, and dark theme CSS`

---

## T9.3: 라이브 테이블 뷰

**Goal**: 실시간으로 게임 상태를 관전할 수 있는 테이블 뷰 페이지를 구현한다.

**Deps**: T9.2, T5.2

**Scope**:
- `app/templates/viewer/table_live.html` — 라이브 테이블 뷰
- `app/api/viewer/views.py` 수정 — 테이블 뷰 라우트 추가
- `app/static/viewer.css` 수정 — 테이블 뷰 스타일 추가
- `app/static/viewer.js` — 폴링 & DOM 업데이트 로직

**AC**:
- [ ] **포커 테이블 비주얼** (CSS/HTML):
  - 타원형 테이블 중앙에 보드카드 5장 + 팟 금액 표시
  - 좌석 9개를 테이블 주위에 배치 (시계 방향)
  - 각 좌석 표시:
    - 닉네임 (봇은 `🤖` 접두사 또는 아이콘 구분)
    - 스택 금액
    - 상태: 빈 자리(회색), 착석(정상), 폴드(반투명), 올인(강조), 현재 턴(테두리 하이라이트)
    - 딜러 버튼(D), SB, BB 마커
  - 보드카드: 카드 이미지 또는 텍스트 표현 (`As`, `Kh` 등 → 수트 색상 구분)
  - 현재 베팅 금액, 액션 타이머 (남은 시간 표시)
- [ ] **액션 피드** (테이블 아래):
  - 최근 액션 로그 (스크롤 가능, 최대 50개)
  - 각 액션: `[seat_no] nickname: ACTION amount` 형태
  - 새 핸드 시작/쇼다운/팟 분배 이벤트도 표시
  - 새 액션은 상단에 추가 (최신순)
- [ ] **팟 정보 패널**:
  - 메인 팟 + 사이드팟 목록 (eligible seats 포함)
  - 총 팟 금액
- [ ] **JavaScript 폴링** (`viewer.js`):
  - `state_version` 기반 변경 감지 — 버전 바뀔 때만 DOM 업데이트
  - 폴링 간격: 2초 (게임 진행 중), 10초 (대기 중)
  - 핸드 완료 시 결과 팝업 (승자, 핸드 랭킹, 팟 분배)
  - 네트워크 오류 시 자동 재시도 (지수 백오프)
- [ ] **현재 핸드 결과 표시**:
  - 쇼다운 시 공개된 홀카드 표시 (핸드 상세 API 호출)
  - 승자 하이라이트 (칩 이동 애니메이션은 선택)
- [ ] `/viewer/tables/{no}` 경로에 인증 없이 접근 가능
- [ ] 존재하지 않는 테이블 번호 시 404 에러 페이지

**Commit**: `feat(viewer): add live table view with poker visual, action feed, and auto-polling`

---

## T9.4: 리더보드 페이지

**Goal**: 전체 플레이어 순위표를 표시하는 리더보드 페이지를 구현한다.

**Deps**: T9.1, T9.2

**Scope**:
- `app/templates/viewer/leaderboard.html` — 리더보드 페이지
- `app/api/viewer/views.py` 수정 — 리더보드 뷰 라우트 추가

**AC**:
- [ ] 리더보드 테이블:
  - 컬럼: 순위, 닉네임, 타입(사람/봇), 총 칩, 수익, 핸드 수, 승률, 최대 팟, 현재 테이블
  - 봇 표시: 닉네임 옆에 봇 타입 뱃지 (`TAG`, `LAG`, `FISH`)
  - 사람: 일반 표시
  - 정렬 변경 가능 (컬럼 헤더 클릭 → `sort_by` 파라미터 변경)
- [ ] 필터:
  - "봇 포함/제외" 토글 버튼
  - 기본: 전체 표시
- [ ] 상위 3명 강조 (금/은/동 색상)
- [ ] 통계 요약 카드:
  - 전체 플레이어 수 (사람/봇 구분)
  - 총 핸드 수
  - 총 발행 칩
- [ ] JavaScript: 60초마다 자동 갱신
- [ ] 반응형: 모바일에서 핵심 컬럼만 표시 (순위, 닉네임, 총 칩, 승률)

**Commit**: `feat(viewer): add leaderboard page with rankings, filters, and statistics`

---

## T9.5: 핸드 히스토리 뷰어

**Goal**: 완료된 핸드의 목록 조회와 상세 리플레이를 제공하는 페이지를 구현한다.

**Deps**: T9.2, T5.3

**Scope**:
- `app/templates/viewer/hand_list.html` — 핸드 목록 페이지
- `app/templates/viewer/hand_detail.html` — 핸드 상세 리플레이 페이지
- `app/api/viewer/views.py` 수정 — 핸드 히스토리 뷰 라우트 추가
- `app/static/viewer.js` 수정 — 리플레이 인터랙션

**AC**:
- [ ] 핸드 목록 페이지 (`/viewer/tables/{no}/hands`):
  - 테이블 번호 헤더
  - 핸드 목록 테이블: Hand #, 보드, 승자, 팟 총액, 시작/종료 시간
  - 커서 기반 페이지네이션 ("이전", "다음" 버튼)
  - 각 핸드 → 상세 페이지 링크
  - 핸드 없으면 "아직 완료된 핸드가 없습니다" 표시
- [ ] 핸드 상세 리플레이 (`/viewer/tables/{no}/hands/{id}`):
  - **핸드 요약**: 테이블, Hand #, 보드카드, 시작/종료 시간
  - **참가자 테이블**: 좌석, 닉네임, 시작 스택, 종료 스택, 손익, 홀카드(공개된 경우)
  - **액션 타임라인**: 스트리트별로 구분된 액션 로그
    - Preflop / Flop / Turn / River / Showdown 섹션
    - 각 액션: `[좌석] 닉네임 — ACTION amount`
    - 시스템 액션 (DEAL, BLIND 등) 구분 스타일
  - **팟 분배 결과**: 메인팟/사이드팟별 승자, 금액, 핸드 랭킹
  - 보드카드 진행: 스트리트별로 보드가 점진적으로 표시 (Flop 3장 → Turn +1장 → River +1장)
- [ ] 핸드가 존재하지 않으면 404 에러 페이지
- [ ] 라이브 테이블 뷰에서 "핸드 히스토리 →" 링크로 연결

**Commit**: `feat(viewer): add hand history list and detailed hand replay pages`

---

# 티켓 요약

| Milestone | Ticket | 제목 | 의존성 |
|-----------|--------|------|--------|
| **M0** | T0.1 | FastAPI 프로젝트 스캐폴드 | — |
| | T0.2 | DB + Alembic + 모델 + 마이그레이션 | T0.1 |
| **M1** | T1.1 | 관리자 인증 + 계정 CRUD | T0.2 |
| | T1.2 | API 키 발급 / 폐기 | T1.1 |
| | T1.3 | HMAC-SHA256 서명 검증 | T1.2 |
| **M1.5** | T1.5.1 | 칩 원장 + 관리자 칩 API | T1.1 |
| **M2** | T2.1 | 테이블 CRUD + 상태 전이 | T1.1 |
| | T2.2 | 착석 / 이석 + 플레이어 API | T2.1, T1.5.1, T1.3 |
| | T2.3 | 공개 테이블 API + /me | T2.2 |
| **M3** | T3.1 | 카드 / 덱 / 핸드 평가기 | T0.1 |
| | T3.2 | 핸드 시작 (블라인드 + 딜링) | T3.1, T2.2 |
| | T3.3 | 베팅 라운드 엔진 | T3.2 |
| | T3.4 | 리걸 액션 계산기 | T3.3 |
| | T3.5 | 라운드 종료 + 스트리트 진행 | T3.3 |
| | T3.6 | 테이블 락 + 액션 API | T3.5, T3.4, T1.3 |
| **M4** | T4.1 | 사이드팟 계산기 | T3.3 |
| | T4.2 | 쇼다운 + 팟 분배 | T4.1, T3.1 |
| | T4.3 | 핸드 완료 + 자동 다음 핸드 | T4.2, T3.5 |
| **M5** | T5.1 | Private 상태 API + 스냅샷 | T3.6, T4.3 |
| | T5.2 | Public 상태 API | T5.1 |
| | T5.3 | 핸드/액션 이력 API | T4.3 |
| **M6** | T6.1 | 자동 폴드 타임아웃 태스크 | T3.6 |
| | T6.2 | Nonce 정리 + 서버 복구 | T4.3, T6.1 |
| **M7** | T7.1 | Admin UI — 계정/키/칩 | T1.5.1, T1.2 |
| | T7.2 | Admin UI — 테이블/게임 | T7.1, T5.3 |
| | T7.3 | Dockerfile + Railway + README | 전체 |
| | T7.4 | 통합 / 시나리오 테스트 | 전체 |
| **M8** | T8.1 | Bot 데이터 모델 + 마이그레이션 | T0.2 |
| | T8.2 | Bot 프리플롭 핸드 레인지 | T8.1, T3.1 |
| | T8.3 | Bot 포스트플롭 의사결정 | T8.2, T3.1 |
| | T8.4 | Bot 러너 백그라운드 태스크 | T8.3, T3.6, T4.3 |
| | T8.5 | Admin Bot 관리 API | T8.1, T2.2 |
| | T8.6 | Admin UI — Bot 관리 | T8.5, T7.1 |
| | T8.7 | Bot 초기화 시드 + 자동 착석 | T8.5, T8.4 |
| | T8.8 | Bot 통합 테스트 | T8.4, T8.5, T8.7 |
| **M9** | T9.1 | 리더보드 통계 API | T5.3 |
| | T9.2 | Viewer 기본 레이아웃 & 로비 | T9.1, T5.2 |
| | T9.3 | 라이브 테이블 뷰 | T9.2, T5.2 |
| | T9.4 | 리더보드 페이지 | T9.1, T9.2 |
| | T9.5 | 핸드 히스토리 뷰어 | T9.2, T5.3 |

**총 티켓: 38개**

---

# 병렬 실행 가능 그룹

의존성 그래프상 다음 티켓들은 병렬 진행 가능:

- **T1.5.1** (칩) ∥ **T1.2** (키) ∥ **T2.1** (테이블) — 모두 T1.1만 의존
- **T3.1** (카드/평가기) — T0.1만 의존하므로 M1/M1.5와 병렬 가능
- **T4.1** (팟 계산기) — T3.3만 의존하므로 T3.4/T3.5와 병렬 가능
- **T5.3** (이력 API) ∥ **T5.1** (Private 상태) — T4.3 완료 후 병렬
- **T6.1** (타임아웃) ∥ **T5.1~5.3** — T3.6 완료 후 병렬
- **T7.1** (Admin UI 계정) — M1.5 완료 후 M3와 병렬 가능
- **T8.2** (프리플롭) ∥ **T8.5** (Bot API) — T8.1 완료 후 병렬
- **T8.6** (Bot UI) — T8.5 완료 후 T8.3/T8.4와 병렬 가능
- **T9.1** (리더보드 API) — T5.3만 의존하므로 M8과 완전 병렬 가능
- **T9.3** (라이브 뷰) ∥ **T9.4** (리더보드 페이지) ∥ **T9.5** (핸드 히스토리) — T9.2 완료 후 병렬
