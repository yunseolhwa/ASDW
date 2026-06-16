# ASDW Fusion Typer Docs

이 폴더는 구현 코드가 아니라 검토용 지식 문서와 검증 기록을 둡니다.

- `fusion-module-knowledge.md`: 퓨전 모듈의 목적, 센서 구성, 웹/Hugging Face 근거, 데이터셋 후보.
- `fusion-review-state.md`: 현재 구현/검증 상태, 검토 가능한 endpoint, 남은 미검증 항목.

현재 서버 스냅샷 report는 `artifacts/fusion-review/latest/report.md`에 생성됩니다.

검토 시작점:

- `artifacts/fusion-review-bundle/latest/report.md`
- 생성 명령: `.\.venv-win\Scripts\python.exe .\scripts\build_fusion_review_bundle.py`

Readiness audit:

- `artifacts/fusion-readiness-audit/latest/report.md`
- 생성 명령: `.\.venv-win\Scripts\python.exe .\scripts\audit_fusion_readiness.py`

Detector와 classifier/fusion 분리 검토 report:

- `artifacts/fusion-review/latest-builtin-detector/report.md`
- `artifacts/fusion-review/latest-label-boxes/report.md`

Schema/safety gate 계약 검증 report:

- `artifacts/fusion-contract/latest/report.md`

Agent observe/rehearse policy smoke:

- `artifacts/agent-policy-smoke/latest/report.md`

WSL ROCm GPU server smoke:

- `artifacts/gpu-server-smoke/latest/report.md`

External GUI dataset metadata readiness report:

- `artifacts/gui-dataset-readiness/latest/report.md`

ScreenSpot-Pro tiny external-box review:

- `artifacts/screenspot-pro-tiny/latest/report.md`
- `artifacts/screenspot-pro-tiny/latest/overlays/`

UI-Elements tiny grounding review:

- `artifacts/ui-elements-tiny/latest/report.md`
- `artifacts/ui-elements-tiny/latest/overlays/`

GroundCUA tiny grounding review:

- `artifacts/groundcua-tiny/latest/report.md`
- `artifacts/groundcua-tiny/latest/overlays/`
