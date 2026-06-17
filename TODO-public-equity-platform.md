# TODO: Public Equity Research Platform

이 문서는 프로젝트를 공개주식 리서치 플랫폼으로 전환한 뒤의 작업 목록입니다.

## 1. 프로젝트 정리

- 루트 문서는 공개주식 테마 리서치 기준으로 유지합니다.
- 새 기능은 `research/public_equity_theme_schema` 아래에 둡니다.
- Codex action과 환경 문서는 주식 DB 검증, DB 생성, 대시보드 실행 중심으로 바꿉니다.
- 저장소 이름은 다음 정리 시점에 `public-equity-theme-research` 같은 이름으로 바꾸는 것을 검토합니다.

## 2. 데이터 모델

- 현재 SQLite 스키마를 유지하면서 실제 provider ingestion layer를 추가합니다.
- 우선 provider 후보:
  - SEC EDGAR submissions/company facts
  - OpenFIGI 식별자 매핑
  - 시장 데이터/estimate provider
  - 내부 watchlist 또는 CSV import
- `raw_payloads`에는 원본 JSON을 보존하고, 분석 필드는 normalized table로 승격합니다.
- stale data 정책은 screen run과 PM session 양쪽에서 확인합니다.

## 3. 리서치 워크플로

- 테마 입력에서 후보 universe를 만드는 `idea-generation` 흐름을 구현합니다.
- 후보별 필수 필드:
  - Why now
  - Variant wedge
  - Exposure proof
  - Expectations risk
  - First rejection
  - What would make it investable
  - What would kill it
  - Next workflow
- 결과는 최종 추천이 아니라 research-priority bucket으로 표시합니다.

## 4. 대시보드

- 현재 Vite 온보딩 대시보드를 PM 작업 화면으로 확장합니다.
- 우선순위:
  - 후보 필터와 세션별 비교
  - evidence drilldown
  - stale data 경고
  - source conflict 표시
  - downstream workflow handoff 표시
- 대시보드 데이터는 SQLite에서 export한 JSON을 기본 입력으로 둡니다.

## 5. 검증

- `validate_public_equity_project.ps1`를 기본 smoke check로 사용합니다.
- 스키마 변경 시 다음을 반드시 통과시킵니다.
  - foreign key check
  - enum/JSON 제약조건
  - duplicate identifier 방지
  - FTS evidence search
  - PM gate/actionability view
  - generated SQLite file integrity

## 6. 보류

- 실제 투자 추천, 포지션 사이징, 매수/매도 명령은 범위 밖입니다.
- 실시간 가격과 consensus 데이터는 provider가 정해질 때까지 seed/demo 데이터로만 다룹니다.
- 투자 리서치와 무관한 실험 코드는 새로 추가하지 않습니다.
