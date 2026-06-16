# TODO: Local Daemon and LLM Controller

이 문서는 Windows 캡처 데몬과 WSL 비전/LLM 컨트롤러를 운영 경로로 고정하기 위한 작업 목록입니다.

## 현재 운영 방식

지금은 필요할 때 Windows 캡처 데몬을 켜고 끕니다.

켜기:

```powershell
cd D:\asdw-fusion-typer
powershell -ExecutionPolicy Bypass -File .\scripts\run_capture_daemon_windows.ps1
```

끄기:

- 데몬을 실행한 PowerShell 창에서 `Ctrl+C`
- 또는 포트 점유 프로세스를 종료

```powershell
Get-NetTCPConnection -LocalPort 7870 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

확인:

```powershell
Invoke-RestMethod http://127.0.0.1:7870/health
```

전체 화면 캡처:

```powershell
Invoke-WebRequest `
  -Uri "http://127.0.0.1:7870/frame?monitor=1" `
  -OutFile D:\asdw-fusion-typer\frame.png
```

스트리밍:

```text
http://127.0.0.1:7870/stream?monitor=1&fps=8
```

## 로컬 LLM 역할

LLM은 비전 분류기가 아니라 action 컨트롤러입니다. 현재 구현은 SGLang OpenAI-compatible endpoint를 우선 사용하고, WSL 서버가 JSON schema로 action을 검증한 뒤 Windows 데몬에 실행을 위임합니다.

- 현재 화면 상태 판정
- 어떤 센서를 더 볼지 결정
- 실패/재시도/중단 판단
- 여러 작업 모드 간 상태 전이
- 액션 JSON 생성

퓨전 모듈은 특정 게임 전용 센서가 아니라 화면 기반 입력 경계입니다. 실험 이미지는 검증 재료일 뿐이며, 대상별 차이는 ROI, 센서 조합, prompt/context, mode policy에서 처리합니다.

현재 퓨전 baseline:

- `template`: 빠른 기준 센서
- `classifier`: 학습된 Hugging Face/timm 분류 센서
- `template,classifier`: 기본 추천 조합
- `clip`, `trocr`, `owlvit`: 웹/Hugging Face 구현을 참고한 후보 센서이며 baseline 승격 전 별도 검증 필요

후보 센서 runtime smoke:

- `clip`: 호출 가능, 샘플에서 `SDWWSWDAA`; 1개 오답으로 baseline 보류
- `trocr`: 호출 가능, 샘플에서는 accepted sequence 없음
- `owlvit`: Transformers API fallback 후 호출 가능, 샘플에서는 accepted sequence 없음

검토 endpoint:

- `GET /fusion/status`
- `POST /predict`
- `POST /grounding/review`

`/fusion/status`는 baseline 센서와 후보 센서를 분리해서 노출합니다. `/predict`는 `fusion.sensor_sequences`, `agreement_rate`, `disagreements`, per-detection `sensor_keys`, `fused_scores`를 반환해 센서 불일치와 최종 융합 판단을 리뷰할 수 있게 합니다.

`/predict`는 optional `boxes`를 받아 built-in detector를 건너뛰고 외부 box proposal을 분류/융합할 수 있습니다. 이 경계는 OmniParser류 GUI parser, accessibility snapshot, target-specific ROI detector를 나중에 얇게 붙이기 위한 접점입니다.

`/grounding/review`는 ASDW classifier와 분리된 일반 GUI evidence endpoint입니다. 외부 provider가 준 bbox/text/label을 검증하고, 정규화 좌표, crop 요약, instruction overlap, rejected box를 반환합니다. 이 endpoint는 모델을 로드하거나 입력하지 않습니다.

검토 report 생성:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --include-candidates
```

결과는 `artifacts/fusion-review/latest/report.md`와 `report.json`에 저장됩니다. 이 스크립트는 입력 endpoint를 호출하지 않습니다.

현재 검토 시작점:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\build_fusion_review_bundle.py
```

결과는 `artifacts/fusion-review-bundle/latest/report.md`와 `report.json`에 저장됩니다. 이 스크립트는 기존 report를 한 곳에 묶고 `/fusion/status`, `/agent/status`, `/llm/check`, daemon `/ping`, `/queue/status`만 safe probe합니다. 입력 endpoint는 호출하지 않습니다.

검토 가능 상태 audit:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\audit_fusion_readiness.py
```

최근 결과는 `reviewable`, `29/29` pass이며 `artifacts/fusion-readiness-audit/latest/report.md`에 저장됩니다. 이 audit는 현재 퓨전 모듈이 사람 검토 가능한 상태인지 확인합니다. live 입력, SGLang runtime, optional provider, 장시간 soak는 완료 처리하지 않고 명시 미검증으로 유지합니다.

서버 없이 schema와 safety gate만 검증:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/verify_fusion_contracts.py"
```

최근 결과는 `19/19` pass이며 `artifacts/fusion-contract/latest/report.md`에 저장됩니다. 이 검증은 daemon endpoint, 모델 로딩, SGLang 호출 없이 LLM action schema, mode policy, confidence gate, external box normalization, generic grounding evidence schema, fusion weighting을 확인합니다.

Agent policy HTTP smoke:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\smoke_agent_policy.py
```

최근 결과는 `4/4` pass이며 `artifacts/agent-policy-smoke/latest/report.md`에 저장됩니다. direct `/agent/act` decision으로 `observe` skip, `rehearse` daemon `dry_run=true`, `live` guard, low-confidence block을 확인합니다. 이 검증은 capture, LLM call, live input을 수행하지 않습니다.

WSL ROCm GPU server smoke:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/smoke_server_wsl_gpu.py --port 7869 --startup-timeout-sec 120 --predict-timeout-sec 180"
```

최근 결과는 `4/4` pass이며 `artifacts/gpu-server-smoke/latest/report.md`에 저장됩니다. 임시 서버에서 `template,classifier` 예측이 `cuda` 장치로 실행되고 sequence `SDWWDWDAA`를 반환하는지 확인합니다. 이 검증은 입력 endpoint를 호출하지 않으며, 장시간 GPU/daemon 안정성 검증은 아닙니다.

Detector와 classifier/fusion을 분리해서 보려면:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --dataset-labels .\artifacts\captcha-tiles\captcha_tiles_800x600\labels.json --max-dataset-samples 20 --dataset-sensors template,classifier --output-dir .\artifacts\fusion-review\latest-builtin-detector
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --dataset-labels .\artifacts\captcha-tiles\captcha_tiles_800x600\labels.json --dataset-use-label-boxes --max-dataset-samples 20 --dataset-sensors template,classifier --output-dir .\artifacts\fusion-review\latest-label-boxes
```

최근 결과:

- built-in detector route: `0/20` sequence accuracy
- external label box route: `19/20` sequence accuracy
- PM 판단: 다음 병목은 classifier가 아니라 범용 box proposal provider

Non-Minecraft GUI dataset readiness:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/gui_dataset_readiness.py"
```

최근 결과는 `artifacts/gui-dataset-readiness/latest/report.md`에 저장됩니다. ScreenSpot-Pro와 GroundCUA는 direct image/annotation 계열이라 다음 일반화 검토 후보입니다. ScreenSpot/RICO parquet 계열은 parquet reader를 baseline에 넣지 않기 위해 보류합니다.

ScreenSpot-Pro tiny external-box review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_screenspot_pro_tiny.py --max-samples 2"
```

최근 결과는 `artifacts/screenspot-pro-tiny/latest/report.md`에 저장됩니다. 두 개의 EViews/Windows high-resolution GUI sample이 `/grounding/review`와 `/predict` external box 경로를 통과했고 overlay가 생성되었습니다. 현재 출력은 A/S/D/W out-of-domain evidence이므로 GUI grounding accuracy로 보지 않습니다.

UI-Elements tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_ui_elements_tiny.py --max-samples 2 --max-elements 12"
```

최근 결과는 `artifacts/ui-elements-tiny/latest/report.md`에 저장됩니다. 두 개의 web/UI sample에서 14개 YOLO bbox가 `/grounding/review`를 통과했고 overlay가 생성되었습니다. 이 검증은 `/predict`나 입력 endpoint를 호출하지 않으며, provider 정확도 검증이 아니라 일반 GUI evidence boundary 검증입니다.

GroundCUA tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_groundcua_tiny.py --max-samples 2 --max-elements 20"
```

최근 결과는 `artifacts/groundcua-tiny/latest/report.md`에 저장됩니다. OBS Studio와 Calibre desktop sample에서 29개 annotation bbox가 `/grounding/review`를 통과했고 overlay가 생성되었습니다. 이 검증은 `/predict`나 입력 endpoint를 호출하지 않으며, 실제 provider 정확도 검증이 아니라 desktop UI evidence boundary 검증입니다.

다음 dataset 작업 후보:

- ScreenSpot-Pro tiny sample: 완료. 다음은 `/grounding/review` 앞단에 OmniParser/provider 후보를 붙일지 결정
- UI-Elements tiny sample: 완료. 다음은 YOLO provider를 runtime dependency로 붙일 필요가 실제로 있는지 별도 판단
- GroundCUA platform subset: 완료. 다음은 live app 화면에서 GroundCUA류 provider가 필요한지 별도 판단

예상 출력:

```json
{
  "state": "captcha_prompt",
  "action": "press_sequence",
  "keys": ["s", "d", "w", "w", "d", "w", "d", "a", "a"],
  "confidence": 0.98,
  "reason": "vision model detected ASDW prompt"
}
```

## 구현된 LLM/agent API

- `POST /llm/check`
  - SGLang-compatible `/v1/models` 상태 확인
  - base URL, 모델명, RTT, 오류 반환
  - 현재 검증: SGLang offline일 때 `ok=false`로 안전 실패 반환; SGLang 실제 런타임/모델 로딩은 미검증
- `POST /agent/step`
  - Windows 데몬 캡처
  - 비전 추론
  - LLM action JSON 생성
  - Pydantic schema 재검증
  - 실제 입력 없음
- `POST /agent/act`
  - `observe`: 입력 없음
  - `rehearse`: Windows 데몬에 `dry_run=true`
  - `live`: `allow_live_input=true`일 때만 실제 입력
- `GET /agent/status`
  - 비전 서버, Windows 데몬, LLM, 마지막 step/act 상태 반환
- `GET /daemon/status`
  - TODO 호환 alias

## Provider API 상태

기본 운영 경로는 계속 Windows `SendInput` 입력과 `mss` 캡처입니다. Provider API는 확장 지점으로만 존재하며, optional provider 후보는 현재 필수 스택이 아닙니다.

- optional dependency 파일
  - `requirements-windows-strong.txt`
  - 포함 후보는 pin 상태: `pywinctl==0.4.1`, `pywinauto==0.6.9`, `pydirectinput-rgx==2.1.3`, `dxcam==0.3.0`
  - `windows-capture`는 주석 처리된 실험 후보
  - baseline 설치 절차에는 포함하지 않음
- `GET /providers`
  - window/input/capture/accessibility provider capability 반환
- target registry
  - `GET /targets`
  - `POST /targets/select`
  - `GET /targets/current`
  - `POST /targets/refresh`
  - baseline은 builtin Win32 API
  - PyWinCtl은 필요 검증 후 실험
- input provider
  - `POST /keys/press`에 `provider = builtin|pydirectinput`
  - dry-run은 provider 설치 여부와 무관하게 큐/타이밍만 검증
  - 한글/IME `type_text`는 builtin 유지
  - 현재 Windows venv에는 `PyDirectInput==1.0.4`가 감지되지만 baseline이 아니며, `pydirectinput-rgx` 후보의 live 동작은 미검증
- capture provider
  - `/frame`, `/stream`, `/frame_base64`, `/predict_once`에 `provider = mss|dxcam|windows_capture`
  - `dxcam`은 ROI/target region 캡처 후보
  - `windows_capture`는 등록된 실험 후보이며 기본 실행 provider로는 아직 미연결
  - optional capture provider 실기 동작은 미검증
- agent 연동
  - `/agent/step`은 frame metadata에 provider/target/region을 포함
  - `/agent/act`는 `target_id`가 stale이면 입력 실행 전 차단
  - press action은 `input_provider`를 daemon `/keys/press`로 전달

## 추가 상태체크 로직

남은 운영 고정 시 다음 상태체크를 더 구체화합니다.

- LLM 서버 상태 확인
  - `/health` 또는 OpenAI-compatible `/v1/models`
  - 응답 지연 시간 기록
  - 모델명 확인
- 비전 서버 상태 확인
  - `http://127.0.0.1:7868/health`
  - GPU 장치 확인
  - 로드된 센서 확인
- 캡처 상태 확인
  - 모니터 목록
  - 마지막 캡처 시간
  - 프레임 크기
  - 스트림 FPS
- 액션 안전 상태
  - 키 입력 활성화 여부
  - dry-run 여부
  - 마지막 입력 시각
  - 연속 실패 횟수

## Windows 운영 데몬 고정 TODO

현재 고정 완료:

- Windows Python 런타임: `.venv-win` / Python 3.12.13
- Python 의존성: `requirements-windows.txt` exact pin
- 설치 도구: `pip==26.1.2`, `wheel==0.47.0`, `setuptools==82.0.1`
- 입력 ABI: `SendInput` 64-bit `INPUT == 40` layout
- 입력 엔진: `SendInputKeyboardAdapter`
- 상태 확인: `/health`, `/ping`, `/queue/status`

아직 운영 데몬으로 고정해야 할 항목:

- Windows Service 등록
  - NSSM, WinSW, 또는 직접 Windows Service wrapper 중 하나로 고정
  - 서비스명 예: `ASDWFusionDaemon`
  - 실행 파일: `D:\asdw-fusion-typer\.venv-win\Scripts\python.exe`
  - 실행 인자: `-m uvicorn asdw_fusion.windows_capture_daemon:app --host 127.0.0.1 --port 7870`
  - 작업 디렉터리: `D:\asdw-fusion-typer`
- 관리자 권한 실행 정책
  - 서비스 계정과 권한 모델 결정
  - `/ping.privilege.is_admin == true`를 운영 기준으로 삼을지 결정
  - UAC/보안 프로그램과 충돌할 때 실패 상태를 `/health`에 노출
- 자동 시작과 재시작 정책
  - Windows 부팅 시 자동 시작
  - 비정상 종료 시 자동 재시작
  - 재시작 backoff와 최대 재시도 횟수 고정
- 로그 경로 고정
  - stdout/stderr 파일 경로 예: `D:\asdw-fusion-typer\logs\daemon.log`
  - 로그 로테이션 정책
  - 마지막 오류를 `/health` 또는 `/daemon/status`에 노출
- 실행 옵션 고정
  - host/port를 환경변수 또는 설정 파일로 고정
  - 외부 접근이 필요하기 전까지 기본 host는 `127.0.0.1`
  - 서비스 모드에서는 reload 금지
- 종료/업데이트 절차 고정
  - 서비스 중지
  - 의존성 drift 확인
  - `ENVIRONMENT_LOCK.md` 검증 명령 실행
  - 서비스 재시작
- 하트비트 운영 기준
  - 서버 heartbeat가 데몬 offline을 감지했을 때 알림/재시작 정책
  - RTT 임계값과 실패 횟수 임계값 정의
  - 데몬 재시작 중 서버 poller가 입력 요청을 보내지 않도록 gate 추가

이 섹션은 실제 서비스화 전까지 TODO로 유지합니다. 구현 시 `ENVIRONMENT_LOCK.md`에 최종 서비스 관리자, 서비스명, 실행 계정, 로그 경로, 시작 유형을 추가합니다.

## API 확장 TODO

- `POST /config`
  - LLM base URL, 모델명, FPS, JPEG 품질, dry-run 설정 변경
- `GET /config`
  - 현재 설정 조회
- agent prompt/profile 버전 노출
- 마지막 LLM raw error와 schema validation error의 요약 노출
- `pywinauto` UIA snapshot endpoint
  - `GET /targets/{id}/uia`
  - 브라우저/앱/런처/설정창 계열에 한정
- `windows_capture` HWND/HMONITOR provider 실험
  - Rust/Python 패키징 확인
  - `capture_target` 실험 endpoint에서만 사용 후 기본 provider 승격 판단

## 로컬 LLM 백엔드 후보

외부 API는 사용하지 않습니다.

- SGLang
  - 상태머신/structured output 컨트롤러 후보
  - OpenAI-compatible endpoint 사용
- vLLM
  - 로컬 LLM serving 후보
  - OpenAI-compatible endpoint 사용
- Ollama 또는 llama.cpp
  - ROCm/SGLang/vLLM이 불안정할 때 fallback 후보

백엔드는 교체 가능하게 둡니다.

```text
ASDW_LLM_BACKEND=sglang|vllm|ollama
ASDW_LLM_BASE_URL=http://127.0.0.1:8000/v1
ASDW_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

## 우선순위

1. 지금은 캡처 데몬을 수동으로 켜고 끄는 방식 유지
2. SGLang 서버 실행 방식과 모델명을 환경 고정
3. agent API를 `observe`/`rehearse`로 반복 검증
4. `live` 모드는 명시 승인 경로로만 사용
5. Windows Service 등록과 재시작 정책 고정
6. `/config` API와 profile 버전 관리 추가

## 주의

- `agent/step`은 입력하지 않습니다.
- `agent/act`의 기본 모드는 `observe`입니다.
- `live` 입력은 `allow_live_input=true` 없이는 실행하지 않습니다.
- schema validation, 낮은 confidence, 빈 비전 결과는 입력을 차단합니다.
- 로컬 모델만 사용합니다.
- 외부 API 의존성을 운영 경로에 넣지 않습니다.
