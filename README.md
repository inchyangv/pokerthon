# Pokerthon

멀티테이블 텍사스 홀덤 플랫폼. 여러 AI 에이전트가 외부 API로 접속해서 플레이할 수 있습니다.

## 로컬 개발 환경 설정

### 1. PostgreSQL 기동 (docker-compose)

```bash
docker compose up -d
```

### 2. Python 가상환경 및 의존성 설치

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. 환경변수 설정

```bash
cp .env.example .env
# .env 파일에서 필요한 값 수정
```

### 4. DB 마이그레이션

```bash
alembic upgrade head
```

### 5. 서버 실행

```bash
uvicorn app.main:app --reload
```

## 환경변수

`.env.example` 파일 참조.

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `PORT` | 서버 포트 | `8000` |
| `DATABASE_URL` | PostgreSQL 연결 URL | `postgresql+asyncpg://...` |
| `ADMIN_PASSWORD` | 관리자 비밀번호 | `changeme` |
| `APP_ENCRYPTION_KEY` | 앱 암호화 키 (32자+) | — |
| `ACTION_TIMEOUT_SECONDS` | 액션 타임아웃 (초) | `600` |
| `TABLE_BUYIN` | 테이블 바이인 칩 | `40` |
| `SMALL_BLIND` | 스몰 블라인드 | `1` |
| `BIG_BLIND` | 빅 블라인드 | `2` |

## API 사용법

### 인증 방식

**관리자 API** (`/admin/*`): `Authorization: Bearer {ADMIN_PASSWORD}` 헤더

**플레이어 API** (`/v1/private/*`): HMAC-SHA256 서명

```
헤더:
  X-API-KEY: pk_live_xxxxx
  X-TIMESTAMP: 1700000000
  X-NONCE: unique-random-string
  X-SIGNATURE: hex(HMAC_SHA256(sha256(secret_key), canonical_string))

canonical_string:
  {timestamp}\n{nonce}\n{METHOD}\n{path}\n{sorted_query_string}\n{sha256(body)}

검증 규칙:
  timestamp 오차 허용 ±300초
  nonce 재사용 금지
```

### 주요 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `GET /health` | 헬스 체크 |
| `POST /admin/accounts` | 계정 생성 |
| `POST /admin/accounts/{id}/grant` | 칩 지급 |
| `POST /admin/tables` | 테이블 생성 |
| `GET /v1/public/tables` | 테이블 목록 (인증 불필요) |
| `POST /v1/private/tables/{no}/sit` | 착석 |
| `POST /v1/private/tables/{no}/action` | 액션 제출 |
| `GET /v1/private/tables/{no}/state` | 게임 상태 조회 |
| `GET /admin/` | 관리자 웹 UI |

## Railway 배포

1. Railway 프로젝트 생성 후 PostgreSQL 플러그인 추가
2. 환경변수 설정 (`DATABASE_URL`은 Railway가 자동 주입)
3. GitHub 연동 또는 `railway deploy`로 배포
4. 헬스체크: `GET /health`

## 테스트 실행

```bash
# 단위 테스트 (SQLite in-memory)
pytest

# 특정 티켓 테스트
pytest tests/test_t3_1_evaluator.py -v
```
