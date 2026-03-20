# DONE_TICKET.md

완료된 티켓 목록 (마일스톤 순).

---

# M0 — Project Bootstrap

## T0.1: FastAPI 프로젝트 스캐폴드
**Commit**: `feat(scaffold): init FastAPI project with directory structure and settings`
**Status**: ✅ DONE

## T0.2: DB 연결 + Alembic + 전체 모델 + 마이그레이션
**Commit**: `feat(db): add SQLAlchemy models, Alembic migration, health check, docker-compose`
**Status**: ✅ DONE

---

# M1 — Accounts & Auth Foundation

## T1.1: 관리자 인증 미들웨어 + 계정 CRUD
**Commit**: `feat(accounts): add admin auth middleware and account CRUD API`
**Status**: ✅ DONE

## T1.2: API 키 발급 / 폐기
**Commit**: `feat(credentials): add API key generation, revocation, and re-issue`
**Status**: ✅ DONE

## T1.3: HMAC-SHA256 서명 검증 미들웨어
**Commit**: `feat(auth): add HMAC-SHA256 signature verification middleware`
**Status**: ✅ DONE

---

# M1.5 — Chip Management

## T1.5.1: 칩 원장 서비스 + 관리자 칩 API
**Commit**: `feat(chips): add chip ledger service and admin grant/deduct API`
**Status**: ✅ DONE

---

# M2 — Tables & Seating

## T2.1: 테이블 CRUD + 상태 전이
**Commit**: `feat(tables): add table CRUD with state machine and admin API`
**Status**: ✅ DONE

## T2.2: 착석 / 이석 서비스 + 플레이어 API
**Commit**: `feat(seating): add sit/stand logic with chip flow and player API`
**Status**: ✅ DONE

## T2.3: 공개 테이블 API + 플레이어 계정 API
**Commit**: `feat(public-api): add public table endpoints and player me endpoint`
**Status**: ✅ DONE

---

# M3 — Core Game Engine

## T3.1: 카드 / 덱 / 핸드 평가기
**Commit**: `feat(cards): add card, deck, and 7-card hand evaluator with tests`
**Status**: ✅ DONE

## T3.2: 핸드 시작 — 블라인드 포스트 + 딜링
**Commit**: `feat(hand-start): implement hand initialization with blinds, dealing, and button rotation`
**Status**: ✅ DONE

## T3.3: 베팅 라운드 엔진 — 액션 처리
**Commit**: `feat(betting): implement action processing with validation rules`
**Status**: ✅ DONE

## T3.4: 리걸 액션 계산기
**Commit**: `feat(legal-actions): implement legal action calculator with min/max raise`
**Status**: ✅ DONE

## T3.5: 베팅 라운드 종료 판단 + 스트리트 진행
**Commit**: `feat(streets): implement round completion detection and street progression`
**Status**: ✅ DONE

## T3.6: 테이블별 동시성 락 + 액션 제출 API
**Commit**: `feat(action-api): add action submission endpoint with per-table locking`
**Status**: ✅ DONE

---

# M4 — Showdown, Pots & Hand Completion

## T4.1: 사이드팟 계산기
**Commit**: `feat(pots): implement side pot calculator from hand contributions`
**Status**: ✅ DONE

## T4.2: 쇼다운 + 승자 결정 + 팟 분배
**Commit**: `feat(showdown): implement showdown resolution with pot distribution`
**Status**: ✅ DONE

## T4.3: 핸드 완료 + 자동 다음 핸드
**Commit**: `feat(hand-complete): implement hand completion, auto-leave, and next hand trigger`
**Status**: ✅ DONE

---

# M5 — Game State APIs & History

## T5.1: Private 게임 상태 API + 스냅샷
**Commit**: `feat(private-state): add private game state API with snapshot and long-poll`
**Status**: ✅ DONE

## T5.2: Public 게임 상태 API
**Commit**: `feat(public-state): add public game state API without hole cards`
**Status**: ✅ DONE

## T5.3: 핸드 이력 + 액션 이력 API
**Commit**: `feat(history): add hand history and action log APIs with pagination`
**Status**: ✅ DONE

---

# M6 — Background Tasks & Recovery

## T6.1: 자동 폴드 타임아웃 백그라운드 태스크
**Commit**: `feat(timeout): add auto-fold timeout background task`
**Status**: ✅ DONE

## T6.2: Nonce 정리 + 서버 재시작 복구
**Commit**: `feat(recovery): add nonce cleanup task and server restart recovery`
**Status**: ✅ DONE

---

# M7 — Admin UI & Deployment

## T7.1: 관리자 웹 UI — 계정/키/칩 관리
**Commit**: `feat(admin-ui): add admin web UI for accounts, credentials, and chips`
**Status**: ✅ DONE

## T7.2: 관리자 웹 UI — 테이블/게임 관리
**Commit**: `feat(admin-ui): add admin web UI for table management and game history`
**Status**: ✅ DONE

## T7.3: Dockerfile + Railway 배포 설정
**Commit**: `feat(deploy): add Dockerfile, Railway config, and README`
**Status**: ✅ DONE

## T7.4: 통합 / 시나리오 테스트
**Commit**: `test(integration): add full game flow integration and scenario tests`
**Status**: ✅ DONE

---

# 전체 요약

| Milestone | 티켓 수 | 상태 |
|-----------|---------|------|
| M0 | 2 | ✅ 완료 |
| M1 | 3 | ✅ 완료 |
| M1.5 | 1 | ✅ 완료 |
| M2 | 3 | ✅ 완료 |
| M3 | 6 | ✅ 완료 |
| M4 | 3 | ✅ 완료 |
| M5 | 3 | ✅ 완료 |
| M6 | 2 | ✅ 완료 |
| M7 | 4 | ✅ 완료 |
| **합계** | **27** | **✅ 전체 완료** |
