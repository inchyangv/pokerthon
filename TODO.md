# TODO: Viewer 성능 최적화 — Phase 2

> 목표: 관전(viewer) 페이지의 **체감 반응성**을 극적으로 개선한다.
> Phase 1 (N+1 제거, 304, incremental feed, 캐시) 완료 상태에서 남은 구조적 병목을 제거한다.
>
> 핵심 지표:
> - 라이브 테이블 업데이트 지연: 현재 0~2000ms → **< 100ms**
> - state 엔드포인트 DB 쿼리: 현재 6회 → **1회**
> - 응답 크기: 현재 ~3KB raw → **< 1KB** (압축)

---

## P0: 서버 인프라 (가장 큰 구조적 병목)

### T1. SSE(Server-Sent Events)로 라이브 테이블 실시간 푸시

- **현상**: `table_live.html`이 2초 간격으로 `/v1/public/tables/{table_no}/state`를 HTTP 폴링.
  상태 변경이 없어도 매번 TCP 연결 + DB 쿼리(최소 version 체크 1회). 상태 변경 시 6회 쿼리.
  평균 업데이트 지연 = polling_interval / 2 = **~1초**.
- **기반**: `snapshot_service.py`에 `wait_for_change(table_id, version, wait_ms)`가 이미 구현되어 있음.
  `asyncio.Event`로 상태 변경을 감지하는 인프라가 있지만 **아무 곳에서도 사용하지 않음**.
- **해결**:
  1. `GET /v1/public/tables/{table_no}/stream` SSE 엔드포인트 추가
  2. 연결 시 현재 state 즉시 전송 (`event: state`)
  3. `wait_for_change()` 대기 → 변경 시 새 state 푸시
  4. action 데이터도 같은 스트림으로 `event: actions` 푸시 (폴링 2개 → SSE 1개)
  5. 클라이언트: `EventSource` API로 수신, 재연결 자동 처리
  6. 기존 폴링은 SSE 미지원 환경 fallback으로 유지
- **파일**: `app/api/public/game_state.py` (신규 엔드포인트), `app/templates/viewer/table_live.html` (JS 교체)
- **기대 효과**: 업데이트 지연 1초 → **< 100ms**, idle 시 DB 쿼리 0, HTTP 연결 수 대폭 감소
- **커밋**: `perf(live): add SSE stream endpoint for real-time table updates`

### T2. DB 인덱스 추가 (핵심 쿼리 경로)

- **현상**: viewer 핵심 쿼리들이 인덱스 없이 순차 스캔.
  - `hands` 테이블: `WHERE table_id = ? AND status = ?` — 모든 state/history 쿼리에서 사용
  - `hand_actions` 테이블: `WHERE hand_id = ? ORDER BY seq` — 액션 피드
  - `hand_players` 테이블: `WHERE hand_id = ?` — 게임 state + 히스토리
  - `chip_ledger` 테이블: `WHERE account_id = ? AND reason_type = ?` — 리더보드
- **파일**: 신규 Alembic migration
- **해결**: 복합 인덱스 추가
  ```sql
  CREATE INDEX ix_hands_table_status ON hands (table_id, status);
  CREATE INDEX ix_hands_table_id_desc ON hands (table_id, id DESC);
  CREATE INDEX ix_hand_actions_hand_seq ON hand_actions (hand_id, seq);
  CREATE INDEX ix_hand_players_hand ON hand_players (hand_id);
  CREATE INDEX ix_chip_ledger_account_reason ON chip_ledger (account_id, reason_type);
  ```
- **기대 효과**: 핸드/액션 수 증가에도 쿼리 시간 일정 (seq scan → index scan)
- **커밋**: `perf(db): add indexes for viewer-critical query paths`

### T3. GZip 응답 압축 활성화

- **현상**: JSON 응답과 HTML 템플릿이 압축 없이 전송됨.
  `PublicGameState` 응답 ~3KB, `leaderboard` 응답 ~8KB 등. JSON은 일반적으로 70-80% 압축 가능.
- **파일**: `app/main.py`
- **해결**: FastAPI `GZipMiddleware` 추가
  ```python
  from starlette.middleware.gzip import GZipMiddleware
  app.add_middleware(GZipMiddleware, minimum_size=500)
  ```
- **기대 효과**: 응답 크기 70% 감소, 모바일/저대역폭 환경에서 체감 큰 개선
- **커밋**: `perf(http): enable gzip compression for all responses`

---

## P1: 백엔드 쿼리 최적화

### T4. 스냅샷 기반 state 서빙 (6 쿼리 → 1 쿼리)

- **현상**: `get_public_game_state()`가 상태 변경 시 6개 직렬 DB 쿼리 실행:
  1. `select(Table)` — 테이블 조회
  2. `get_snapshot_version()` — 스냅샷 버전 조회
  3. `select(TableSeat)` — 좌석 목록
  4. `select(Account)` — 닉네임 매핑
  5. `select(Hand)` — 진행 중 핸드
  6. `select(HandPlayer)` — 핸드 플레이어
  이 중 `bump_snapshot()`이 이미 `snapshot_json`에 데이터를 저장하지만, **읽는 곳이 없음**.
- **파일**: `app/api/public/game_state.py:50-164`, `app/services/snapshot_service.py:21-52`
- **해결**:
  1. `bump_snapshot()` 호출 시점에 `PublicGameState` 전체를 `snapshot_json`으로 저장
  2. `get_public_game_state()`에서 `TableSnapshot` 1건만 조회 → JSON 파싱 → 응답
  3. version 미변경 시 기존처럼 304 반환
- **주의**: snapshot 저장 시점의 데이터 정합성 확인 필요 (트랜잭션 내에서 저장)
- **기대 효과**: state 응답 DB 쿼리 6회 → **1회**, 응답 시간 50%+ 단축
- **커밋**: `perf(game-state): serve pre-computed snapshot instead of re-querying`

### T5. `get_latest_hand_actions()` SQL 레벨 필터링

- **현상**: 현재 로직:
  1. 최신 핸드 조회 (1 쿼리)
  2. `get_hand_actions()` 호출 → **모든** 액션 로드 + 닉네임 매핑 (2 쿼리)
  3. Python에서 `after_seq` 필터링
  핸드 중반 이후 액션 50개 중 49개를 로드 후 버리는 구조.
- **파일**: `app/services/history_service.py:263-288`
- **해결**:
  1. `after_seq`가 있으면 SQL `WHERE seq > after_seq` 직접 적용
  2. 닉네임 매핑도 필터링된 액션의 `actor_account_id`만 대상으로 축소
  ```python
  q = select(HandAction).where(
      HandAction.hand_id == hand.id,
      HandAction.seq > after_seq
  ).order_by(HandAction.seq)
  ```
- **기대 효과**: 인크리멘탈 폴링 시 데이터 로드 90% 감소
- **커밋**: `perf(actions): filter by after_seq at SQL level`

### T6. 로비 API 누락 필드 추가 (correctness + perf)

- **현상**: `PublicTableList` 스키마에 `hand_id`, `small_blind`, `big_blind` 없음.
  로비 JS에서 `t.hand_id`로 LIVE 뱃지, `t.small_blind/big_blind`로 블라인드 표시 → **첫 JS 갱신 후 깨짐**.
  별도 API 호출 없이 해결해야 함.
- **파일**: `app/schemas/table_public.py:25-30`, `app/api/public/tables.py:14-29`
- **해결**:
  1. `PublicTableList`에 `hand_id: int | None`, `small_blind: int`, `big_blind: int` 추가
  2. `list_public_tables()`에서 active hand 조회 (1 batch query) + blind 정보 포함
  3. 로비 뷰도 동일 API 활용하도록 통일 가능
- **기대 효과**: LIVE 뱃지 정상 작동 + 블라인드 표시 유지 + 추가 API 호출 불필요
- **커밋**: `fix(lobby-api): add hand_id and blind fields to public table list`

---

## P2: 프론트엔드 / 자산 최적화

### T7. Google Fonts 셀프 호스팅

- **현상**: 매 페이지 로드 시 `fonts.googleapis.com` + `fonts.gstatic.com`에 외부 요청.
  non-blocking 처리(media=print trick)되어 있지만 여전히:
  - DNS lookup 2회 (googleapis.com, gstatic.com)
  - CSS 파일 fetch 1회
  - WOFF2 파일 fetch 2~4회
  총 ~200-400ms 외부 네트워크 지연.
- **파일**: `app/templates/viewer/base.html:7-15`
- **해결**:
  1. Inter (wght 400,500,600,700) + JetBrains Mono (wght 400,700) WOFF2 다운로드
  2. `app/static/fonts/` 에 배치
  3. `viewer.css` 최상단에 `@font-face` 선언 (`font-display: swap`)
  4. `base.html`에서 Google Fonts `<link>` 제거
- **기대 효과**: 외부 네트워크 의존 제거, FCP 200-400ms 단축
- **커밋**: `perf(fonts): self-host Inter and JetBrains Mono`

### T8. game_state 쿼리 병렬화 (asyncio.gather)

- **현상**: T4(스냅샷 서빙)가 적용되기 전 혹은 fallback 경로에서,
  6개 DB 쿼리가 모두 `await` 직렬 실행. 각 쿼리 ~2-5ms라면 총 12-30ms.
- **파일**: `app/api/public/game_state.py:56-118`
- **해결**: 독립적인 쿼리들을 `asyncio.gather()`로 병렬 실행
  ```python
  seats_result, hand_result = await asyncio.gather(
      session.execute(select(TableSeat).where(...)),
      session.execute(select(Hand).where(...)),
  )
  ```
  주의: 같은 session 공유 시 asyncpg 동시 실행 불가 → 별도 session 또는 순차유지 판단 필요.
  실질적으로는 T4 적용 후 이 경로를 안 타므로 **T4와 순서 조율**.
- **기대 효과**: fallback 경로 응답 시간 30-50% 단축
- **커밋**: `perf(game-state): parallelize independent DB queries`

### T9. 로비 SSE 스트림

- **현상**: 로비가 5~30초 간격으로 `/v1/public/tables` 폴링.
  테이블 상태 변경(핸드 시작/종료, 좌석 변경)을 즉시 반영 못함.
- **파일**: `app/templates/viewer/lobby.html:108-184`
- **해결**:
  1. `GET /v1/public/tables/stream` SSE 엔드포인트
  2. 어떤 테이블이든 `bump_snapshot()` 발생 시 → 전체 테이블 목록 푸시
  3. 클라이언트: `EventSource`로 수신, 기존 DOM 업데이트 로직 재활용
- **기대 효과**: 로비도 실시간 업데이트, 폴링 제거
- **커밋**: `perf(lobby): add SSE stream for real-time table list updates`

### T10. CSS critical path 최적화

- **현상**: `viewer.css` 685줄 전체가 render-blocking.
  실제 첫 화면 렌더에 필요한 CSS는 약 100줄 (nav, container, 기본 타이포).
- **파일**: `app/templates/viewer/base.html:17`, `app/static/viewer.css`
- **해결**:
  1. 첫 렌더에 필수인 CSS를 `<style>` 인라인으로 `<head>`에 삽입
  2. 나머지 viewer.css는 `media=print` + `onload` 트릭으로 non-blocking 로드 (폰트와 동일 패턴)
  3. 또는 `<link rel="preload" as="style">`
- **기대 효과**: FCP 추가 50-100ms 단축
- **커밋**: `perf(css): inline critical CSS for faster first paint`

---

## P3: 추가 개선 (Nice to Have)

### T11. connection pool 튜닝

- **현상**: `create_async_engine()` 기본 pool_size=5, max_overflow=10.
  동시 viewer 접속이 많으면 커넥션 대기 발생 가능.
- **파일**: `app/database.py:13`
- **해결**: viewer 트래픽 패턴에 맞게 pool_size/max_overflow 조정
  ```python
  create_async_engine(_db_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
  ```
- **커밋**: `perf(db): tune connection pool for viewer concurrency`

### T12. 정적 자산 content hash 기반 장기 캐시

- **현상**: 현재 `Cache-Control: public, max-age=3600` (1시간).
  CSS/JS 변경 시 브라우저가 오래된 캐시를 사용할 수 있음.
- **해결**:
  1. 빌드/배포 시 파일 해시를 파일명에 포함 (`viewer.abc123.css`)
  2. `max-age=31536000` (1년)으로 설정
  3. HTML 템플릿에서 해시된 파일명 참조
- **커밋**: `perf(static): content-hash filenames for immutable caching`

### T13. 리더보드 leaderboard_service 쿼리 경량화

- **현상**: `get_leaderboard()`가 모든 accounts의 전체 HandPlayer를 로드 후 메모리에서 집계.
  핸드 수가 증가하면 메모리/시간이 선형 증가.
- **해결**:
  1. `hand_players` + `hands` JOIN 집계를 SQL `GROUP BY`로 이동
  2. `COUNT(*)`, `SUM(CASE WHEN ...)` 등 DB 레벨 집계
  3. 또는 `materialized view` / 집계 테이블 도입
- **커밋**: `perf(leaderboard): move aggregation to SQL GROUP BY`

---

## 작업 우선순위 요약

| 순서 | 티켓 | 병목 유형 | 난이도 | 기대 효과 |
|------|------|-----------|--------|-----------|
| 1 | **T2** DB 인덱스 | DB | 낮 | 모든 쿼리 즉시 개선 |
| 2 | **T3** GZip 압축 | 네트워크 | 낮 | 응답 크기 70%↓ |
| 3 | **T6** 로비 API 누락 필드 | 정확성+성능 | 낮 | LIVE 뱃지 수정 |
| 4 | **T5** 액션 쿼리 SQL 필터 | DB | 낮 | 인크리멘탈 쿼리 90%↓ |
| 5 | **T4** 스냅샷 기반 서빙 | DB | 중 | 6 쿼리 → 1 쿼리 |
| 6 | **T1** SSE 라이브 스트림 | 아키텍처 | 높 | 지연 1s → <100ms |
| 7 | **T7** 폰트 셀프호스팅 | 자산 | 낮 | FCP 200-400ms↓ |
| 8 | **T9** 로비 SSE | 아키텍처 | 중 | 로비도 실시간 |
| 9 | **T10** Critical CSS | 자산 | 낮 | FCP 50-100ms↓ |
| 10 | **T8** 쿼리 병렬화 | DB | 중 | fallback 30-50%↓ |
| 11 | **T11** 커넥션 풀 | DB | 낮 | 동시접속 안정성 |
| 12 | **T12** 해시 기반 캐시 | 자산 | 중 | 캐시 적중률 극대화 |
| 13 | **T13** 리더보드 SQL 집계 | DB | 높 | 핸드 증가 시 스케일 |

> **권장 실행 순서**: T2 → T3 → T6 → T5 → T4 → T1 (쉬운 것부터, 가장 큰 아키텍처 변경은 마지막)
