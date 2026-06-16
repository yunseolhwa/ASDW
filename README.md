# ASDW Fusion Typer

Minecraft 화면 중앙에 뜨는 `A`, `S`, `D`, `W` 프롬프트를 캡처해서 왼쪽부터 하나씩 입력하는 실험 프로젝트입니다.

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

- `template`: OpenCV 버튼 분할과 글자 템플릿 매칭. 빠르고 실제 입력의 주 센서입니다.
- `classifier`: 이 프로젝트에서 전이학습한 Hugging Face/timm MobileNetV3 분류기입니다.
- `clip`: `openai/clip-vit-base-patch32` 제로샷 이미지-텍스트 분류.
- `trocr`: `microsoft/trocr-small-printed` OCR 센서. 느리지만 실험용으로 유용합니다.
- `owlvit`: `google/owlvit-base-patch32` 제로샷 객체 감지. 이 UI에는 과하지만 멀티모달 감지 실험용입니다.

분류 모델 학습 후 추천 시작값은 `template,classifier`입니다. 더 무겁게 실험하려면 `template,classifier,clip,trocr,owlvit`로 바꾸세요.

기본 융합 가중치는 학습된 `classifier`를 주 분류기로, `template`을 보조 센서로 둡니다. 픽셀 폰트가 달라지면 `ASDW_WEIGHT_TEMPLATE`, `ASDW_WEIGHT_CLASSIFIER`, `ASDW_WEIGHT_CLIP` 환경변수로 조정할 수 있습니다.

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

강한 Windows provider는 optional입니다. 기본 운영 경로는 계속 `builtin` 입력과 `mss` 캡처입니다.

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r requirements-windows-strong.txt
Invoke-RestMethod "http://127.0.0.1:7870/providers"
Invoke-RestMethod "http://127.0.0.1:7870/targets"
```

지원 provider:

- target registry: `pywinctl` 우선, 실패 시 builtin Win32 fallback
- input: `/keys/press`의 `provider = "builtin" | "pydirectinput"`
- capture: `/frame_base64`의 `provider = "mss" | "dxcam" | "windows_capture"`
- accessibility 후보: `pywinauto`는 dependency/capability만 노출하고, UIA snapshot API는 다음 단계에서 붙입니다.

`windows_capture`는 실험 후보로 등록만 되어 있으며 기본 경로에서는 사용하지 않습니다.

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

DirectX/게임 호환 입력을 실험하려면 optional dependency 설치 후 `provider = "pydirectinput"`를 지정합니다. 한글/IME 텍스트 입력은 계속 builtin 경로를 사용합니다.

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

기본 ROI는 첨부된 Minecraft 화면 기준 입력 버튼 줄입니다.

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
