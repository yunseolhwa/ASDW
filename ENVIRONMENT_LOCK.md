# ASDW Fusion Typer Environment Definition

Last verified: 2026-06-17 KST

이 문서는 lockfile이 아니라 현재 운영 기준 스택 정의서입니다. 목적은 새 의존성을 늘리는 것이 아니라, 필요한 최소 기술스택과 검증 상태를 분리해서 버전 차이로 생기는 버그를 줄이는 것입니다.

## Design Rule

- LLM이 판단하고, 입력 부서는 검증, 모드 정책, 실행, 상태 노출만 담당합니다.
- 입력 부서는 LLM보다 무거운 자동화 프레임워크가 되면 안 됩니다.
- 목표는 인간의 일반적인 컴퓨터 활용력을 넘어 여러 시나리오에 대응하는 것이지만, 구현은 얇고 안정적으로 유지합니다.
- 새 라이브러리는 "없으면 해결할 수 없는 문제"가 확인될 때만 baseline에 넣습니다.

## Minimum Baseline Stack

### Windows Daemon

역할: 화면 캡처, 키 입력 실행, 큐 처리, 안전 상태 노출.

```text
OS: Microsoft Windows NT 10.0.26100.0
PowerShell: 7.6.2
Python: 3.12.13
Virtualenv: D:\asdw-fusion-typer\.venv-win
pip: 26.1.2
wheel: 0.47.0
setuptools: 82.0.1
```

필수 직접 의존성:

```text
fastapi==0.137.1
mss==10.2.0
pillow==12.2.0
requests==2.34.2
uvicorn==0.49.0
```

핵심 표준/OS 의존:

```text
ctypes SendInput
Windows IMM/IME APIs
Win32 window APIs
```

`pydantic==2.13.4`, `starlette==1.3.1` 등은 현재 설치되어 있지만 FastAPI 계열 전이 의존성입니다. 제품 판단 기준의 핵심 스택으로 취급하지 않습니다.

### WSL ROCm Server

역할: 비전 추론, 로컬 LLM action 컨트롤러, daemon heartbeat/poller.

```text
Distro: Ubuntu-24.04-ROCmLab
Python: 3.12.3
Virtualenv: /mnt/d/asdw-fusion-typer/.venv-wsl
GPU: AMD Radeon RX 6600 XT
pip: 26.1.2
wheel: 0.47.0
setuptools: 70.2.0
```

필수 직접 의존성:

```text
accelerate==1.14.0
fastapi==0.137.1
huggingface_hub==1.19.0
numpy==2.4.4
opencv-python-headless==4.13.0.92
pillow==12.2.0
protobuf==7.35.1
pydantic==2.13.4
python-multipart==0.0.32
requests==2.34.2
safetensors==0.8.0
sentencepiece==0.2.1
timm==1.0.27
transformers==5.12.0
uvicorn==0.49.0
```

ROCm/PyTorch 기준:

```text
torch==2.11.0+rocm7.2
torchvision==0.26.0+rocm7.2
torchaudio==2.11.0+rocm7.2
triton-rocm==3.6.0
```

ROCm runtime flags used by `scripts/run_server_wsl.ps1`:

```text
HSA_ENABLE_SDMA=0
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

### Local LLM Link

LLM은 입력 실행부가 아니라 action 판단부입니다. 연결 방식은 OpenAI-compatible local endpoint를 기준으로 합니다.

```text
Default target: SGLang-compatible /v1 endpoint
ASDW_LLM_BASE_URL=http://127.0.0.1:8000/v1
ASDW_LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

SGLang 자체 버전은 이 repo venv 안에서 검증되지 않았습니다. LLM 서버는 별도 프로세스로 취급하며, `/llm/check`로 연결성만 검증합니다.

## Optional Candidates Are Not Baseline

아래 후보는 현재 필수 스택이 아닙니다. 기본 운영 경로를 대체하지 않는 단순 추가라면 설치하지 않습니다.

```text
pywinctl==0.4.1
pywinauto==0.6.9
pydirectinput-rgx==2.1.3
dxcam==0.3.0
windows-capture
```

현재 기준:

- baseline input: `ctypes SendInput`
- baseline capture: `mss`
- baseline target state: builtin Win32 APIs
- optional provider는 실제 문제와 필요가 확인될 때만 실험합니다.
- optional provider 실험 결과가 좋아도, LLM보다 무거운 입력 부서가 되면 baseline으로 승격하지 않습니다.
- current Windows venv note: `PyDirectInput==1.0.4` is installed and `/providers` can detect `pydirectinput`, but it is not part of `requirements-windows.txt`, not the `pydirectinput-rgx` candidate, and not live-verified.

## Verification Status

검증됨:

| Area | Status | Evidence |
| --- | --- | --- |
| Windows Python/tooling | Verified | `Python 3.12.13`, `pip 26.1.2` |
| Windows core dependency versions | Verified | `fastapi`, `mss`, `pillow`, `requests`, `uvicorn` versions matched baseline |
| Windows syntax | Verified | `py_compile` passed for daemon/server/client modules |
| Windows daemon safe HTTP smoke | Verified | `/providers`, `/targets`, `/keys/press` dry-run, stale `hwnd:0` refresh |
| SendInput ABI shape | Verified previously | expected 64-bit `INPUT` layout is documented below |
| WSL Python/tooling | Verified | `Python 3.12.3`, `pip 26.1.2` |
| WSL server import/compile | Verified | `.venv-wsl` import and `py_compile` passed |
| WSL ROCm visibility | Verified with warning | `torch.cuda.is_available() == True`, device `AMD Radeon RX 6600 XT`; driver-old warning observed |
| WSL ROCm GPU server smoke | Verified one-shot | temporary WSL server on port `7869` ran `POST /predict` with `template,classifier`; `prediction.device == cuda`, post-predict status `device == cuda`, sequence `SDWWDWDAA`; first load latency about `44.2s` |
| Fusion server health | Verified | `GET /health` returned `ok=true`, `cv2=true`; current background review server reports `device=cuda` after classifier load |
| Fusion status endpoint | Verified | `GET /fusion/status` exposes baseline/candidate sensors, evidence endpoints, roles, weights, loaded models, model paths, and runtime device |
| Fusion review summary | Verified | `POST /predict` includes `fusion.sensor_sequences`, `agreement_rate`, `disagreements`, per-detection `sensor_keys`, and `fused_scores` |
| Fusion review report harness | Verified | `scripts/review_fusion_server.py --include-candidates` wrote `artifacts/fusion-review/latest/report.md` and `report.json`; it only calls `/fusion/status` and `/predict` |
| Fusion review bundle | Verified | Windows `.venv-win` ran `scripts/build_fusion_review_bundle.py`; it wrote `artifacts/fusion-review-bundle/latest/report.md` and safe-probed status endpoints without calling input endpoints |
| Fusion readiness audit | Verified | WSL `.venv-wsl` ran `scripts/audit_fusion_readiness.py`; `31/31` checks passed and wrote `artifacts/fusion-readiness-audit/latest/report.md` |
| Fusion contract verifier | Verified | WSL `.venv-wsl` ran `scripts/verify_fusion_contracts.py`; `21/21` contracts passed and wrote `artifacts/fusion-contract/latest/report.md` |
| Agent policy HTTP smoke | Verified | Windows `.venv-win` ran `scripts/smoke_agent_policy.py`; `4/4` cases passed for observe skip, rehearse dry-run, live guard, and low-confidence block without capture, LLM call, or live input |
| Agent step inline smoke | Verified | WSL `.venv-wsl` ran `scripts/smoke_agent_step_inline.py`; inline image -> `/predict` -> `vision_rule` -> `press_sequence` action JSON returned sequence `SDWWDWDAA` with warm latency about `150 ms`; no daemon capture, LLM call, or live input |
| Generic grounding review endpoint | Verified | `POST /grounding/review` accepted external GUI bbox evidence and returned normalized box, crop summary, area ratio, and instruction overlap without model loading or input |
| GUI dataset metadata readiness | Verified metadata only | WSL `.venv-wsl` ran `scripts/gui_dataset_readiness.py`; Hugging Face metadata was inspected for ScreenSpot, ScreenSpot-Pro, GroundCUA, RICO-ScreenQA, and UI-Elements without large downloads |
| ScreenSpot-Pro tiny external-box flow | Verified flow, not accuracy | WSL `.venv-wsl` ran `scripts/review_screenspot_pro_tiny.py --max-samples 2`; two high-resolution GUI samples used `/grounding/review` and external `boxes` in `/predict`, then wrote overlays/report without input endpoints |
| UI-Elements tiny grounding flow | Verified flow, not provider accuracy | WSL `.venv-wsl` ran `scripts/review_ui_elements_tiny.py --max-samples 2 --max-elements 12`; 14 YOLO UI element boxes across two web samples were accepted by `/grounding/review` and overlays/report were written without `/predict` or input endpoints |
| GroundCUA tiny grounding flow | Verified flow, not provider accuracy | WSL `.venv-wsl` ran `scripts/review_groundcua_tiny.py --max-samples 2 --max-elements 20`; 29 desktop UI annotation boxes across OBS Studio and Calibre samples were accepted by `/grounding/review` and overlays/report were written without `/predict` or input endpoints |
| LLM check offline guard | Verified safe failure | With no SGLang server on `127.0.0.1:8000`, `POST /llm/check` returns `ok=false` after the check timeout and `/agent/status` exposes the LLM error without sending input |
| External box prediction path | Verified | `POST /predict` accepts optional `boxes`; used label boxes on 20 synthetic samples without calling input endpoints |
| Template-only prediction | Verified | `template` returned 9 detections on `detection-bboxes-clean.png`; raw sensor sequence was `AASSAWAAA`, accepted sequence was incorrect `AASSAAAA` |
| Classifier prediction | Verified | `classifier` returned `SDWWDWDAA` after first model load |
| Template+classifier fusion | Verified | `template,classifier` returned `SDWWDWDAA`; observed warm server latency was about 0.10-0.18s on CPU review server |
| Dataset with built-in detector | Verified limitation | 20 synthetic samples returned `0/20` sequence accuracy and `0/20` exact detection count; detector is layout-specific |
| Dataset with external label boxes | Verified | 20 synthetic samples returned `19/20` sequence accuracy and `20/20` exact detection count with `template,classifier` |
| CLIP candidate runtime | Verified, not baseline | `clip` returned `SDWWSWDAA`; warm reports were about 1.0-1.5s, one observed wrong key |
| TrOCR candidate runtime | Verified, not baseline | `trocr` returned no accepted sequence; raw sensor sequence `AAAAAAAAA`; warm reports were about 1.5-1.9s |
| OWL-ViT candidate runtime | Verified, not baseline | compatibility fallback added for Transformers `post_process_grounded_object_detection`; returned no accepted sequence; warm reports were about 0.5s |

미검증:

| Area | Status | Notes |
| --- | --- | --- |
| Live key input | Not verified | `live + allow_live_input=true` was intentionally not run |
| Optional input provider | Not verified | `pydirectinput-rgx` not promoted to baseline |
| Optional capture provider | Not verified | `dxcam` not promoted to baseline |
| Optional accessibility provider | Not verified | `pywinauto` UIA snapshot not implemented as baseline |
| Long-running daemon stability | Not verified | needs separate soak test |
| Long-running GPU server stability | Not verified | GPU one-shot smoke passed; soak and warm-latency distribution not measured |
| Game/app-specific compatibility | Not verified | needs per-target scenario test |
| SGLang server runtime version | Not verified in repo venv | only OpenAI-compatible endpoint contract is assumed |
| Candidate sensor generalization | Not verified | CLIP/TrOCR/OWL-ViT were only smoke-tested on the review sample and are not promoted to baseline |
| External GUI grounding accuracy | Not verified | ScreenSpot-Pro, UI-Elements, and GroundCUA tiny flows exist, but they validate evidence plumbing, not real provider accuracy or task success |

Known caveat:

- A direct one-off classifier load outside `scripts/run_server_wsl.ps1` hit a ROCm SDMA assertion. Treat direct ad-hoc ROCm commands without the runtime flags as invalid verification.
- The current background review server exposes latest `/fusion/status`, but classifier inference can be observed on CPU when launched through hidden Windows `Start-Process`. The separate GPU smoke report is the source of truth for the one-shot ROCm server check. It does not replace a long-running GPU soak test.

## Drift Check Commands

Windows:

```powershell
.\.venv-win\Scripts\python.exe --version
.\.venv-win\Scripts\python.exe -m pip --version
.\.venv-win\Scripts\python.exe -m pip freeze --all
.\.venv-win\Scripts\python.exe -m py_compile .\asdw_fusion\windows_capture_daemon.py .\asdw_fusion\server.py .\asdw_fusion\client_windows.py .\scripts\review_fusion_server.py .\scripts\verify_fusion_contracts.py .\scripts\gui_dataset_readiness.py .\scripts\review_screenspot_pro_tiny.py .\scripts\review_ui_elements_tiny.py .\scripts\review_groundcua_tiny.py .\scripts\build_fusion_review_bundle.py .\scripts\audit_fusion_readiness.py .\scripts\smoke_agent_policy.py .\scripts\smoke_agent_step_inline.py .\scripts\smoke_server_wsl_gpu.py .\scripts\build_fusion_showcase.py
```

WSL:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python --version"
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python -m pip freeze --all"
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python -m py_compile asdw_fusion/server.py asdw_fusion/client_windows.py scripts/review_fusion_server.py scripts/verify_fusion_contracts.py scripts/gui_dataset_readiness.py scripts/review_screenspot_pro_tiny.py scripts/review_ui_elements_tiny.py scripts/review_groundcua_tiny.py scripts/build_fusion_review_bundle.py scripts/audit_fusion_readiness.py scripts/smoke_agent_policy.py scripts/smoke_agent_step_inline.py scripts/smoke_server_wsl_gpu.py scripts/build_fusion_showcase.py"
```

ROCm:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')
PY"
```

## SendInput ABI Guard

The Windows daemon uses `ctypes` with the 64-bit Windows `INPUT` layout. If `SendInput` returns `[WinError 87] The parameter is incorrect`, check these sizes first:

```powershell
.\.venv-win\Scripts\python.exe -c "import ctypes; from asdw_fusion.windows_capture_daemon import INPUT, KEYBDINPUT, MOUSEINPUT; print(ctypes.sizeof(ctypes.c_void_p)); print(ctypes.sizeof(KEYBDINPUT)); print(ctypes.sizeof(MOUSEINPUT)); print(ctypes.sizeof(INPUT))"
```

Expected output:

```text
8
24
32
40
```

## Operational Lock Status

The development/runtime stack is defined here. The Windows daemon is not yet locked as an operating-system service.

Remaining operational items are tracked in `TODO-local-daemon-and-llm.md`:

- Windows Service registration
- administrator privilege policy
- automatic start and restart policy
- fixed log path and rotation
- fixed service host/port/options
- update and rollback procedure
- heartbeat-based restart/alert policy
