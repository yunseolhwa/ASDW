# Public Equity Theme Research

공개주식 테마를 투자 리서치 큐로 바꾸는 로컬 프로젝트입니다. 현재 기준점은 `codex/investing` 브랜치의 `13c3f94 온보드` 커밋입니다.

이 저장소의 핵심 산출물은 다음 두 가지입니다.

- `research/public_equity_theme_schema/`: 공개주식 테마 스크리닝용 SQLite 스키마, seed 데이터, 검증 스크립트
- `research/public_equity_theme_schema/visual_onboarding/`: PM 세션, 후보 종목, 게이트, 스키마 맵을 보여주는 React/Vite 온보딩 대시보드

이 프로젝트는 최종 매수/매도 추천 엔진이 아닙니다. 목적은 테마 후보를 `심화 리서치`, `트리거 대기`, `노출 증거 부족`, `제외` 같은 리서치 우선순위로 분류하는 것입니다.

## 현재 범위

- 테마, 수혜 경로, 후보 종목, 증거, 시장 데이터, 밸류에이션 snapshot을 정규화합니다.
- 동일 후보를 `public_equity_diligence`, `long_short_hf`, `long_only_pm` 세션에서 따로 평가합니다.
- source-backed exposure가 없는 후보는 advance 대상이 되지 않도록 gate를 둡니다.
- 원본 provider payload와 사람이 읽는 evidence excerpt를 분리해서 보관합니다.
- 시각화 대시보드는 SQLite 요약 JSON을 읽어 PM 보드, workflow cockpit, schema map을 보여줍니다.

## 빠른 실행

PowerShell에서 저장소 루트로 이동합니다.

```powershell
cd <repository-root>
```

스키마와 seed 데이터를 검증합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\validate_public_equity_project.ps1
```

SQLite DB와 대시보드용 JSON을 생성합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_public_equity_database.ps1
```

온보딩 대시보드를 로컬에서 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_public_equity_dashboard.ps1
```

기본 URL은 `http://127.0.0.1:5173`입니다.

대시보드 실행에는 Node.js와 npm이 필요합니다. 현재 Codex 기본 Python 검증은 Node 없이도 실행됩니다.

## 주요 파일

- `research/public_equity_theme_schema/schema.sql`: SQLite DDL, 제약조건, trigger, view
- `research/public_equity_theme_schema/seed_demo.sql`: AI infrastructure 샘플 테마 seed
- `research/public_equity_theme_schema/seed_pm_sessions.sql`: PM 세션별 평가 seed
- `research/public_equity_theme_schema/build_theme_database.py`: SQLite 파일 생성기
- `research/public_equity_theme_schema/tests/validate_schema.py`: 스키마/seed 기본 검증
- `research/public_equity_theme_schema/tests/validate_pm_database.py`: PM 세션과 파일 DB 검증
- `research/public_equity_theme_schema/visual_onboarding/export_dashboard_data.py`: 대시보드 JSON 생성
- `research/public_equity_theme_schema/visual_onboarding/src/App.tsx`: 온보딩 UI
- `TODO-public-equity-platform.md`: 다음 구현 로드맵

## 운영 원칙

- 티커만 식별자로 쓰지 않습니다. `securities`와 `security_identifiers`를 분리합니다.
- raw payload와 normalized facts를 분리합니다.
- 테마 노출은 주문, backlog, 매출, margin, estimate revision 같은 source-backed evidence가 있어야 합니다.
- keyword-only 후보는 `Exposure not yet proven`으로 남깁니다.
- stale market data는 screen 기준일 대비 별도로 표시합니다.
- PM 세션별 결론은 섞지 않고 독립적으로 유지합니다.

## 프로젝트 방향

새 작업은 `research/public_equity_theme_schema` 아래 주식 리서치 흐름에 맞춥니다.
