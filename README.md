# ASDW Fusion Typer

화면에 나타나는 `A`, `S`, `D`, `W` 계열 프롬프트를 여러 센서로 읽고, 검증된 action만 Windows 입력 경계로 넘기는 로컬 퓨전 입력 프로젝트입니다.

Minecraft는 실험 환경 중 하나입니다. 이 프로젝트의 중심은 특정 게임 전용 센서가 아니라, 화면 캡처, 비전 센서, 로컬 LLM 판단, 입력 안전 정책을 얇게 결합하는 퓨전 모듈입니다.

구조는 두 프로세스와 한 개의 agent 컨트롤 계층입니다.

- WSL ROCm: Hugging Face/OpenCV 기반 비전 추론 서버와 로컬 LLM agent 컨트롤러
- Windows: 화면 캡처와 `SendInput` 키 입력을 담당하는 캡처 데몬
- Legacy Windows client: `client_windows.py`는 직접 캡처/입력 디버그용으로만 유지

Windows 데몬 API의 키 입력 기본값은 실제 입력입니다. 검증만 할 때는 요청에 `dry_run = $true`를 명시하세요.
Agent 계열 API의 기본 모드는 `observe`라 실제 입력을 보내지 않습니다.

## Codex 프로젝트 설정

Codex 앱 Local Environment용 ASDW 설정은 `.codex/README.md`에 고정했습니다.

권장 구성:

- Setup script: `powershell -ExecutionPolicy Bypass -File .\scripts\codex_setup_windows.ps1`
- Action `Start Windows daemon`: `powershell -ExecutionPolicy Bypass -File .\scripts\run_capture_daemon_windows.ps1`
- Action `Start WSL model server`: `powershell -ExecutionPolicy Bypass -File .\scripts\run_server_wsl.ps1`
- Action `Check ASDW status`: `powershell -ExecutionPolicy Bypass -File .\scripts\codex_status.ps1`
- Action `Run Python compile check`: `powershell -ExecutionPolicy Bypass -File .\scripts\codex_py_compile.ps1`
- Action `Clean ASDW temp files`: `powershell -ExecutionPolicy Bypass -File .\scripts\codex_cleanup.ps1`

데몬은 화면 캡처와 키 입력 권한을 다루므로 setup script에서 자동 실행하지 않고 명시적인 Action으로만 켭니다.

## 모델/센서

- `template`: OpenCV 분할과 글자 템플릿 매칭. 매우 빠른 기준 센서입니다.
- `classifier`: 이 프로젝트에서 전이학습한 Hugging Face/timm MobileNetV3 분류기입니다.
- `clip`: `openai/clip-vit-base-patch32` 제로샷 이미지-텍스트 분류 후보입니다.
- `trocr`: `microsoft/trocr-small-printed` OCR 후보입니다.
- `owlvit`: `google/owlvit-base-patch32` open-vocabulary 객체 감지 후보입니다.

추천 시작값은 `template,classifier`입니다. 더 무겁게 실험하려면 `clip`, `trocr`, `owlvit`를 추가할 수 있지만 baseline은 아닙니다.

기본 융합 가중치는 학습된 `classifier`를 주 분류기로, `template`을 보조 센서로 둡니다. 픽셀 폰트나 대상 UI가 달라지면 `ASDW_WEIGHT_TEMPLATE`, `ASDW_WEIGHT_CLASSIFIER`, `ASDW_WEIGHT_CLIP` 환경변수로 조정할 수 있습니다.

현재 서버의 퓨전 상태는 다음 endpoint에서 확인합니다.

```text
GET http://127.0.0.1:7868/fusion/status
```

이미 서버가 떠 있다면 재시작 후 반영됩니다.

`/predict` 응답은 기존 `sequence_text` 외에 검토용 `fusion` 요약을 포함합니다. 여기에는 센서별 raw sequence, accepted/rejected 개수, 센서 불일치 위치, 각 detection의 `fused_scores`와 `sensor_keys`가 들어갑니다. 요청에 `boxes`를 넣으면 built-in detector를 건너뛰고 외부 box 후보를 바로 분류/융합합니다.

일반 GUI element provider는 `/grounding/review`를 먼저 통과시키는 구조입니다. 이 endpoint는 외부 bbox/text/label을 검증하고, 정규화 bbox, 면적, crop 요약, instruction overlap을 반환합니다. ASDW classifier를 억지로 일반 GUI 분류기로 쓰지 않기 위한 얇은 evidence 경계입니다.

구현 참고:

- Hugging Face image classification: `AutoImageProcessor`와 `AutoModelForImageClassification` 기반 로컬 분류기 ([docs](https://huggingface.co/docs/transformers/en/tasks/image_classification))
- Hugging Face CLIP/zero-shot image classification: 학습 없이 후보 label을 비교하는 보조 센서 ([docs](https://huggingface.co/docs/transformers/en/tasks/zero_shot_image_classification))
- Hugging Face TrOCR: OCR 후보 센서 ([docs](https://huggingface.co/docs/transformers/en/model_doc/trocr))
- Hugging Face OWL-ViT: open-vocabulary detection 후보 센서 ([docs](https://huggingface.co/docs/transformers/en/model_doc/owlvit))
- Microsoft OmniParser V2: GUI screenshot을 구조화된 interactable element로 바꾸는 강한 후보지만, 현재 baseline에는 넣지 않습니다 ([GitHub](https://github.com/microsoft/OmniParser), [model card](https://huggingface.co/microsoft/OmniParser-v2.0))
- SGLang structured outputs: action JSON을 schema로 제한하는 LLM controller 근거입니다 ([docs](https://docs.sglang.io/docs/advanced_features/structured_outputs))

이 후보들은 모두 작은 센서를 조합하는 방향이지만, LLM보다 무거운 입력 부서가 되면 baseline으로 승격하지 않습니다.

## 퓨전 모듈 검토 상태

현재 검토 가능한 경로:

- `POST /predict`: 이미지 1장을 받아 센서별 vote와 융합 결과를 반환합니다.
- `POST /grounding/review`: 외부 GUI element bbox/text/label을 받아 일반 grounding evidence를 반환합니다.
- `GET /fusion/status`: 사용 가능한 센서, 현재 로드된 센서, 가중치, 모델 경로를 반환합니다.
- `POST /agent/step`: 캡처, 비전 추론, LLM action 판단까지만 수행하고 입력하지 않습니다.
- `POST /agent/act`: 모드 정책을 통과한 action만 Windows daemon으로 넘깁니다.

전체 검토 진입점은 review bundle입니다. 기존 report를 모으고 현재 server/daemon/LLM 상태를 safe probe로 기록합니다. 입력 endpoint는 호출하지 않습니다.

```powershell
.\.venv-win\Scripts\python.exe .\scripts\build_fusion_review_bundle.py
```

출력:

```text
artifacts/fusion-review-bundle/latest/report.md
artifacts/fusion-review-bundle/latest/report.json
```

review bundle이 사람 검토 가능한 상태인지 한 번에 판정하려면 readiness audit를 실행합니다.

```powershell
.\.venv-win\Scripts\python.exe .\scripts\audit_fusion_readiness.py
```

출력:

```text
artifacts/fusion-readiness-audit/latest/report.md
artifacts/fusion-readiness-audit/latest/report.json
```

현재 audit는 `reviewable`일 때만 성공 종료합니다. 이것은 live 입력, SGLang runtime, optional provider, 장시간 안정성까지 완료됐다는 뜻이 아니라, 그 미검증 항목이 숨겨지지 않고 검토 자료에 분리되어 있다는 뜻입니다.

검토 report를 파일로 남기려면 다음 명령을 실행합니다. 이 스크립트는 `/fusion/status`와 `/predict`만 호출하며 입력 endpoint는 호출하지 않습니다.

```powershell
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --include-candidates
```

기존 synthetic dataset 일부를 함께 평가하려면 다음처럼 실행합니다. `--dataset-use-label-boxes`는 정답 box를 외부 proposal로 넣어 detector와 classifier/fusion을 분리해서 봅니다.

```powershell
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --include-candidates --dataset-labels .\artifacts\captcha-tiles\captcha_tiles_800x600\labels.json --dataset-use-label-boxes --max-dataset-samples 20 --dataset-sensors template,classifier
```

출력:

```text
artifacts/fusion-review/latest/report.md
artifacts/fusion-review/latest/report.json
```

비교용 report:

```text
artifacts/fusion-review/latest-label-boxes/report.md
artifacts/fusion-review/latest-builtin-detector/report.md
```

서버 없이 schema와 safety gate만 빠르게 검증하려면:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/verify_fusion_contracts.py"
```

출력:

```text
artifacts/fusion-contract/latest/report.md
artifacts/fusion-contract/latest/report.json
```

LLM을 호출하지 않고 `/agent/act`의 observe/rehearse/live guard만 HTTP 수준에서 확인하려면:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\smoke_agent_policy.py
```

출력:

```text
artifacts/agent-policy-smoke/latest/report.md
artifacts/agent-policy-smoke/latest/report.json
```

WSL ROCm 임시 서버를 별도 포트로 띄워 GPU 기반 `/predict` 1회를 확인하려면:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/smoke_server_wsl_gpu.py --port 7869 --startup-timeout-sec 120 --predict-timeout-sec 180"
```

출력:

```text
artifacts/gpu-server-smoke/latest/report.md
artifacts/gpu-server-smoke/latest/report.json
```

이 smoke는 임시 서버의 `template,classifier` 예측이 `cuda` 장치에서 실행되는지 확인합니다. 장시간 안정성이나 실제 앱/게임 호환성 검증은 아닙니다.

최근 안전 검증 결과:

| Sensors | Result | Notes |
| --- | --- | --- |
| `template` | `AASSAAAA`, 9 detections | raw sensor sequence는 `AASSAWAAA`; 1개가 confidence 기준 아래라 sequence에서 제외 |
| `classifier` | `SDWWDWDAA`, 9 detections | 첫 로드는 수십 초 걸릴 수 있고 이후 정답 |
| `template,classifier` | `SDWWDWDAA`, 9 detections | warm 상태 약 0.10-0.18초; 센서 agreement rate `0.3333` |
| `clip` | `SDWWSWDAA`, 9 detections | 호출 가능하지만 샘플에서 1개 오답; warm 상태 약 1.0-1.5초 |
| `trocr` | accepted sequence 없음 | raw sensor sequence `AAAAAAAAA`; warm 상태 약 1.5-1.9초 |
| `owlvit` | accepted sequence 없음 | Transformers API fallback 적용 후 500 없이 응답; warm 상태 약 0.5초 |

검증 이미지는 `artifacts/visual-checks/detection-bboxes-clean.png`입니다. 이 이미지는 실험 샘플이며 제품 범위를 특정 게임으로 제한하지 않습니다.

Dataset 검증 요약:

| Route | Samples | Result | Meaning |
| --- | ---: | --- | --- |
| built-in detector + `template,classifier` | 20 | `0/20` sequence, `0/20` exact detection count | 현재 built-in detector는 중앙 한 줄 prompt에 맞춰져 있어 타일형 layout에는 부적합 |
| label boxes + `template,classifier` | 20 | `19/20` sequence, `20/20` detection count | box proposal이 주어지면 classifier/fusion은 강하게 작동 |

PM 판단: 다음 병목은 ASDW classifier가 아니라 범용 box proposal입니다. 그래서 OmniParser류 GUI parser는 baseline 의존성이 아니라, 필요할 때 붙일 수 있는 external `boxes` provider 후보로 보는 게 맞습니다.

Non-Minecraft GUI 데이터셋은 metadata readiness부터 확인합니다. 이 명령은 Hugging Face repo metadata만 읽고 대용량 파일은 다운로드하지 않습니다.

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/gui_dataset_readiness.py"
```

출력:

```text
artifacts/gui-dataset-readiness/latest/report.md
artifacts/gui-dataset-readiness/latest/report.json
```

현재 판단은 ScreenSpot-Pro와 GroundCUA subset을 다음 일반화 검토 후보로 두고, parquet 기반 ScreenSpot/RICO는 baseline 의존성에 넣지 않는 것입니다.

ScreenSpot-Pro tiny sample로 external `boxes` 경로를 확인하려면:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_screenspot_pro_tiny.py --max-samples 2"
```

출력:

```text
artifacts/screenspot-pro-tiny/latest/report.md
artifacts/screenspot-pro-tiny/latest/overlays/
```

이 report는 실제 high-resolution GUI benchmark box가 `/grounding/review`와 `/predict`로 들어가는지 확인합니다. 현재 A/S/D/W classifier 출력은 out-of-domain이므로 GUI grounding 정확도로 해석하지 않습니다.

UI-Elements tiny sample로 일반 web/UI element bbox evidence 경계를 확인하려면:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_ui_elements_tiny.py --max-samples 2 --max-elements 12"
```

출력:

```text
artifacts/ui-elements-tiny/latest/report.md
artifacts/ui-elements-tiny/latest/overlays/
```

이 report는 YOLO annotation을 외부 provider 결과처럼 `/grounding/review`에 넣어 다중 UI element box가 정규화되고 crop evidence로 남는지 확인합니다. `/predict`나 입력 endpoint는 호출하지 않으며, provider 정확도 검증도 아닙니다.

GroundCUA tiny sample로 desktop app annotation bbox evidence 경계를 확인하려면:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_groundcua_tiny.py --max-samples 2 --max-elements 20"
```

출력:

```text
artifacts/groundcua-tiny/latest/report.md
artifacts/groundcua-tiny/latest/overlays/
```

이 report는 GroundCUA의 `data/<platform>/*.json` annotation을 외부 provider 결과처럼 `/grounding/review`에 넣습니다. 현재 tiny smoke는 OBS Studio와 Calibre 샘플의 29개 bbox를 accepted 처리했으며, `/predict`나 입력 endpoint는 호출하지 않습니다.

현재 리뷰용으로 백그라운드에서 띄운 7868 서버는 최신 `/fusion/status`를 제공하지만 classifier device가 CPU로 잡힐 수 있습니다. 별도 GPU smoke는 임시 7869 서버에서 `prediction.device == "cuda"`, post-predict status `device == "cuda"`, sequence `SDWWDWDAA`를 확인했습니다. 장시간 GPU/daemon 안정성은 아직 별도 검증 대상입니다.

## 분류 모델 전이학습

첨부 스크린샷의 버튼 crop을 기준으로 강한 증강 데이터셋을 만들고, `timm/mobilenetv3_small_100.lamb_in1k`의 백본은 고정한 채 classifier head만 ROCm GPU에서 학습합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_train_classifier_wsl.ps1
```

결과 모델은 `D:\asdw-fusion-typer\models\asdw-mobilenetv3-classifier\best`에 저장됩니다.

## 설치

터미널/OS/Python/ROCm/의존성 고정값은 `ENVIRONMENT_LOCK.md`에 기록되어 있습니다. 재설치나 디버깅 전에는 이 문서를 기준으로 버전 드리프트를 확인하세요.

PowerShell에서:

```powershell
cd D:\asdw-fusion-typer
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && bash scripts/setup_wsl_rocm.sh"
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && bash scripts/download_models.sh"
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows_client.ps1
```

## 실행

서버:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_server_wsl.ps1 -Sensors "template,classifier"
```

Legacy 클라이언트 dry-run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_client_windows.ps1 -Sensors "template,classifier" -DebugDir "D:\asdw-fusion-typer\debug"
```

Legacy 클라이언트 실제 입력:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_client_windows.ps1 -Sensors "template,classifier" -LiveInput
```

운영 경로는 Windows 캡처 데몬과 WSL 서버 API입니다. `client_windows.py`는 데몬 경로가 깨졌을 때 비교 검증하는 직접 실행 도구로만 쓰세요.

## Windows 캡처 데몬

Windows 쪽에 상주 API를 띄워서 필요할 때 화면을 가져오거나 WSL 모델 서버로 1회 전달할 수 있습니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_capture_daemon_windows.ps1
```

끄기는 실행 중인 PowerShell 창에서 `Ctrl+C`를 누르면 됩니다. 포트만 기준으로 강제 종료해야 할 때는:

```powershell
Get-NetTCPConnection -LocalPort 7870 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess -Unique |
  ForEach-Object { Stop-Process -Id $_ -Force }
```

주요 endpoint:

```text
GET  http://127.0.0.1:7870/health
GET  http://127.0.0.1:7870/ping
GET  http://127.0.0.1:7870/providers
GET  http://127.0.0.1:7870/targets
POST http://127.0.0.1:7870/targets/select
GET  http://127.0.0.1:7870/targets/current
POST http://127.0.0.1:7870/targets/refresh
GET  http://127.0.0.1:7870/frame?monitor=1
GET  http://127.0.0.1:7870/stream?monitor=1&fps=8
GET  http://127.0.0.1:7870/queue/status
POST http://127.0.0.1:7870/predict_once
POST http://127.0.0.1:7870/keys/press
POST http://127.0.0.1:7870/text/type_keys
POST http://127.0.0.1:7870/predict_and_press
```

기본은 사용자가 보는 모니터 전체 화면입니다. `roi=0.34 0.46 0.66 0.57` 같은 값을 줄 때만 잘라서 보냅니다.

현재 baseline은 최소 스택입니다. 기본 운영 경로는 계속 Windows `SendInput` 입력과 `mss` 캡처입니다.

```powershell
Invoke-RestMethod "http://127.0.0.1:7870/providers"
Invoke-RestMethod "http://127.0.0.1:7870/targets"
```

Optional provider 후보는 기본 설치 대상이 아닙니다. 기존 경로로 해결할 수 없는 문제가 확인될 때만 `requirements-windows-strong.txt`를 실험용으로 사용합니다.

실험 후보:

- target registry: `pywinctl==0.4.1`
- input: `pydirectinput-rgx==2.1.3`
- capture: `dxcam==0.3.0`, `windows-capture` experimental
- accessibility: `pywinauto==0.6.9`

이 후보들은 아직 baseline 작동 검증 완료 항목이 아닙니다.

`predict_once` 예:

```powershell
$body = @{
  model_url = "http://127.0.0.1:7868/predict"
  monitor = 1
  sensors = @("template", "classifier")
  debug = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7870/predict_once" -ContentType "application/json" -Body $body
```

키 입력:

데몬의 키 입력은 Windows `SendInput` 기반 단일 입력 어댑터와 작업 대기열을 통과합니다. 기본값은 라이브성 우선이라 새 요청이 들어오면 이전 대기 작업과 진행 중인 작업을 취소하고 최신 요청을 수행합니다.

```powershell
$body = @{
  keys = "SDWWDWDAA"
  dry_run = $false
  provider = "builtin"
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7870/keys/press" -ContentType "application/json" -Body $body
```

DirectX/게임 호환 입력 후보는 아직 baseline이 아닙니다. 한글/IME 텍스트 입력은 계속 builtin 경로를 사용합니다.

순서가 중요한 작업은 대기열을 유지합니다:

```powershell
$body = @{
  keys = "ASDW"
  dry_run = $false
  queue = @{
    keep_queue = $true
    wait = $true
    timeout_sec = 30
  }
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7870/keys/press" -ContentType "application/json" -Body $body
```

한글 키 입력:

데몬은 입력 전에 현재 포커스 창의 키보드 레이아웃이 한국어인지 확인합니다. 혼합 문장은 한글 구간에서 IME를 켜고, 영문/숫자 구간에서 IME를 꺼서 입력합니다. 예를 들어 `안녕하세요 hello`는 한글 구간을 `dkssudgktpdy`로 입력한 뒤 `hello` 직전에 IME를 끕니다.

```powershell
$body = @{
  text = "안녕하세요"
  dry_run = $false
  require_korean_ime = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7870/text/type_keys" -ContentType "application/json" -Body $body
```

타이밍을 직접 지정:

```powershell
$body = @{
  keys = "SDWWDWDAA"
  dry_run = $false
  timing = @{
    initial_delay_ms = @(80, 220)
    hold_ms = @(28, 55)
    between_ms = @(45, 85)
    long_pause_chance = 0.04
    long_pause_ms = @(140, 280)
  }
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7870/keys/press" -ContentType "application/json" -Body $body
```

캡처, 모델 추론, 키 입력을 한 번에 수행하려면 `/predict_and_press`를 씁니다. 기본은 실제 입력입니다. 입력 없이 검증만 하려면 요청에 `dry_run = $true`를 넣습니다.

## 서버 주도 5초 폴링

서버가 5초마다 Windows 데몬에서 전체 화면을 가져오고, 서버 모델로 처리한 뒤 감지된 `A/S/D/W` 키를 데몬에 다시 보내 입력할 수 있습니다. 자동 루프는 기본으로 꺼져 있고, 필요할 때 켭니다.

한 번만 검증:

```powershell
$body = @{
  daemon_url = "http://127.0.0.1:7870"
  interval_sec = 5
  monitor = 1
  sensors = @("template", "classifier")
  min_confidence = 0.30
  dry_run = $true
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/poller/tick" -ContentType "application/json" -Body $body
```

5초 루프 시작:

```powershell
$body = @{
  daemon_url = "http://127.0.0.1:7870"
  interval_sec = 5
  monitor = 1
  sensors = @("template", "classifier")
  min_confidence = 0.30
  dry_run = $false
  keep_daemon_queue = $false
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/poller/start" -ContentType "application/json" -Body $body
```

상태 확인과 중지:

```powershell
Invoke-RestMethod -Method Get  -Uri "http://127.0.0.1:7868/poller/status"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/poller/stop"
```

WSL 서버에서 Windows 데몬의 `127.0.0.1:7870`에 접근이 안 되면 `daemon_url`을 Windows 호스트 IP로 바꾸고, 데몬을 접근 가능한 주소로 띄우세요.

## 서버 주도 하트비트

서버는 데몬의 `/ping`을 주기적으로 호출해 RTT를 계산하고 online/offline 상태로 사용합니다.

```powershell
$body = @{
  daemon_url = "http://127.0.0.1:7870"
  interval_sec = 2
  timeout_sec = 1
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/heartbeat/start" -ContentType "application/json" -Body $body
Invoke-RestMethod -Method Get  -Uri "http://127.0.0.1:7868/heartbeat/status"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/heartbeat/stop"
```

로컬 LLM 상태머신 확장 계획은 `TODO-local-daemon-and-llm.md`에 정리했습니다.

## LLM agent 컨트롤러

WSL 서버는 SGLang OpenAI-compatible endpoint를 우선 사용해 action JSON을 생성합니다. 기본값:

```text
ASDW_LLM_BASE_URL=http://127.0.0.1:8000/v1
ASDW_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
ASDW_AGENT_MIN_CONFIDENCE=0.60
```

Agent action schema:

```json
{
  "state": "idle|captcha_prompt|typing_prompt|blocked|unknown|error",
  "action": "none|press_sequence|type_text|retry_capture|stop",
  "keys": ["A", "S", "D", "W"],
  "text": "optional text",
  "confidence": 0.0,
  "reason": "short reason"
}
```

주요 endpoint:

```text
POST http://127.0.0.1:7868/llm/check
POST http://127.0.0.1:7868/agent/step
POST http://127.0.0.1:7868/agent/act
GET  http://127.0.0.1:7868/agent/status
GET  http://127.0.0.1:7868/daemon/status
```

`/llm/check`는 SGLang이 켜져 있는지 보는 안전 확인용입니다. 현재 SGLang이 꺼져 있으면 `ok=false`와 오류를 반환하고, 이 상태에서는 `/agent/act`가 실제 입력을 진행할 근거가 없습니다.

`/agent/step`은 캡처, 비전 추론, LLM 판단까지만 수행하고 입력하지 않습니다.

```powershell
$body = @{
  daemon_url = "http://127.0.0.1:7870"
  monitor = 1
  capture_provider = "mss"
  sensors = @("template", "classifier")
  mode = "observe"
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/agent/step" -ContentType "application/json" -Body $body
```

`/agent/act`는 모드별 안전 정책을 적용합니다.

- `observe`: 기본값. 입력하지 않습니다.
- `rehearse`: daemon에 `dry_run=true`로 보내 큐와 타이밍만 검증합니다.
- `live`: 실제 입력입니다. 반드시 `allow_live_input = $true`를 같이 보내야 합니다.

```powershell
$body = @{
  daemon_url = "http://127.0.0.1:7870"
  monitor = 1
  capture_provider = "mss"
  input_provider = "builtin"
  sensors = @("template", "classifier")
  mode = "rehearse"
} | ConvertTo-Json -Depth 4

Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:7868/agent/act" -ContentType "application/json" -Body $body
```

## ROI 조정

현재 샘플 ROI는 첨부된 실험 화면의 입력 버튼 줄입니다.

```text
left top right bottom = 0.34 0.46 0.66 0.57
```

프롬프트 위치가 다르면 다음처럼 조정합니다.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_client_windows.ps1 -RoiFrac "0.32 0.45 0.68 0.58" -DebugDir "D:\asdw-fusion-typer\debug"
```

`debug` 폴더의 PNG/JSON을 보면 서버가 어떤 버튼을 잡았는지 확인할 수 있습니다.

## 참고

WSL에서 PyTorch는 ROCm을 `cuda` 장치처럼 노출합니다. `torch.cuda.is_available()`가 `True`이면 ROCm GPU 추론이 활성화된 상태입니다.

현재 WSL/ROCm 조합에서 GPU 모델 로딩 중 `SDMAQueue` assert가 나면 `HSA_ENABLE_SDMA=0`을 설정하세요. RX 6600 XT처럼 `gfx1032`가 rocBLAS 라이브러리 목록에 없으면 `HSA_OVERRIDE_GFX_VERSION=10.3.0`도 필요합니다. 제공된 서버 실행 스크립트에는 두 값이 기본으로 들어가 있습니다.
