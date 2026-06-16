# Fusion Module Knowledge Base

Last updated: 2026-06-17 KST

## Position

ASDW Fusion Typer의 퓨전 모듈은 특정 게임 전용 센서가 아닙니다. 목적은 화면에 나타난 입력 프롬프트나 UI 단서를 여러 작은 센서로 읽고, LLM action controller가 안전하게 실행할 수 있는 구조화된 evidence를 만드는 것입니다.

Minecraft는 현재 실험 환경 중 하나입니다. 대상별 차이는 ROI, sensor 조합, prompt/context, mode policy에서 처리하고, 퓨전 모듈 자체를 Minecraft 전용으로 만들지 않습니다.

## Current Fusion Shape

현재 baseline은 작고 명확합니다.

- `template`: OpenCV 기반 분할 + 템플릿 점수. 빠르지만 단독 판단은 약할 수 있습니다.
- `classifier`: Hugging Face/timm MobileNetV3 계열 로컬 분류기. 현재 핵심 분류 센서입니다.
- `template,classifier`: 추천 baseline 조합입니다.
- `clip`, `trocr`, `owlvit`: 멀티모달 후보 센서입니다. baseline으로 승격하려면 별도 런타임 검증이 필요합니다.

현재 구현은 `POST /predict`에서 센서별 vote를 만들고, `fuse_votes()`에서 가중 평균과 margin 기반 confidence를 계산합니다. `GET /fusion/status`는 현재 사용 가능한 센서, 로드된 센서, 가중치, 모델 경로를 노출합니다.

`POST /predict`는 optional `boxes`도 받습니다. 이 값이 있으면 built-in detector를 건너뛰고 외부 box proposal을 분류/융합합니다. 이렇게 detector와 classifier/fusion을 분리하면 특정 실험 화면의 box detector에 매몰되지 않고, OmniParser류 GUI parser, accessibility tree, target-specific ROI detector를 얇게 연결할 수 있습니다.

`POST /grounding/review`는 ASDW classifier와 분리된 일반 GUI evidence 경계입니다. 외부 provider가 준 bbox/text/label을 받아 좌표 정규화, crop 요약, instruction overlap, rejected box를 반환합니다. 이 endpoint는 LLM action controller가 읽을 수 있는 구조화 evidence를 만들지만, 입력 실행과 모델 추론은 하지 않습니다.

현재 후보 센서 판정:

- `clip`: runtime smoke는 통과했지만 현재 샘플에서 오답이 있어 baseline은 아닙니다.
- `trocr`: runtime smoke는 통과했지만 현재 샘플에서는 accepted sequence를 만들지 못했습니다.
- `owlvit`: Transformers API 호환 fallback 적용 후 500 없이 응답하지만 현재 샘플에서는 accepted sequence를 만들지 못했습니다.

현재 dataset 검증 해석:

- built-in detector는 중앙 한 줄 prompt에 맞춰져 있어 타일형 synthetic dataset 20개에서는 `0/20` sequence accuracy였습니다.
- 같은 20개 샘플에서 label boxes를 외부 proposal로 넣으면 `template,classifier`가 `19/20` sequence accuracy를 냈습니다.
- 따라서 다음 일반화 병목은 letter classifier보다 box proposal provider입니다.

## Web Research And Imported Patterns

현재 구현은 새 프레임워크를 만들기보다 Hugging Face/Transformers의 검증된 사용 패턴을 얇게 이식합니다.

- Image classification: Hugging Face는 image classification을 이미지에 label/class를 할당하는 task로 설명합니다. 현재 `classifier`는 이 패턴에 맞춰 `AutoImageProcessor`와 `AutoModelForImageClassification`로 로컬 분류기를 로드합니다. Source: [Hugging Face image classification docs](https://huggingface.co/docs/transformers/en/tasks/image_classification).
- Auto classes: Transformers의 Auto classes는 model/config/processor 계열을 checkpoint 경로에서 자동으로 선택하는 방식입니다. 현재 로컬 classifier 로딩 방식과 맞습니다. Source: [Hugging Face Auto Classes docs](https://huggingface.co/docs/transformers/en/model_doc/auto).
- CLIP/zero-shot image classification: Hugging Face는 zero-shot image classification을 명시적 학습 없이 후보 category로 이미지를 분류하는 task로 설명합니다. 이 프로젝트에서는 새로운 UI label 후보를 빠르게 실험하는 보조 센서 후보입니다. Sources: [zero-shot image classification docs](https://huggingface.co/docs/transformers/en/tasks/zero_shot_image_classification), [CLIP docs](https://huggingface.co/docs/transformers/en/model_doc/clip).
- TrOCR: Hugging Face는 TrOCR을 visual understanding과 text generation을 함께 쓰는 text recognition 모델로 설명합니다. 이 프로젝트에서는 버튼/프롬프트가 문자인 경우의 OCR 후보입니다. Source: [TrOCR docs](https://huggingface.co/docs/transformers/en/model_doc/trocr).
- OWL-ViT: Hugging Face는 OWL-ViT를 text query로 이미지 안 object를 찾는 open-vocabulary object detection 모델로 설명합니다. 이 프로젝트에서는 UI element 또는 prompt 영역을 텍스트 질의로 찾는 후보입니다. Source: [OWL-ViT docs](https://huggingface.co/docs/transformers/en/model_doc/owlvit).
- OmniParser V2: Microsoft의 OmniParser는 screenshot을 structured UI element로 바꿔 LLM 기반 GUI agent가 action을 grounding하기 쉽게 만드는 방향입니다. 다만 V2 model card는 icon detection 쪽 AGPL license를 명시하고, repo도 별도 weights/download/runtime 흐름을 요구합니다. 따라서 현재 baseline에는 넣지 않고, 범용 GUI element parsing이 "없으면 불가능한 문제"로 확인될 때 실험 후보로 둡니다. Sources: [OmniParser GitHub](https://github.com/microsoft/OmniParser), [OmniParser V2 model card](https://huggingface.co/microsoft/OmniParser-v2.0), [Microsoft Research blog](https://www.microsoft.com/en-us/research/articles/omniparser-v2-turning-any-llm-into-a-computer-use-agent/).
- SGLang structured outputs: SGLang은 OpenAI-compatible API에서 JSON schema 기반 constrained output을 지원합니다. 현재 agent action schema를 Pydantic으로 정의하고 재검증하는 구조는 이 방식과 맞습니다. Source: [SGLang structured outputs docs](https://docs.sglang.io/docs/advanced_features/structured_outputs).

## Community Provider Candidates

아래 후보는 "직접 새 프레임워크를 만들지 않고, 검증된 구현을 얇게 붙인다"는 원칙에서 조사한 provider 후보입니다. 현재 baseline이 아니며, 실제 문제가 확인될 때만 실험합니다.

- PyWinCtl: window title, active window, position/size, activate/restore 계열 기능을 제공하는 window registry 후보입니다. README는 "get info on and control windows on screen" 용도를 설명하고, watchdog으로 window state change callback을 받을 수 있음을 설명합니다. Source: [Kalmat/PyWinCtl](https://github.com/Kalmat/PyWinCtl).
- pywinauto: Windows GUI 자동화 후보입니다. README는 Microsoft Windows GUI 자동화 모듈이며 Win32 backend와 UI Automation backend를 지원한다고 설명합니다. 이 프로젝트에서는 브라우저/앱/런처/설정창처럼 텍스트와 control tree가 있는 대상에만 맞습니다. Sources: [pywinauto GitHub](https://github.com/pywinauto/pywinauto), [pywinauto docs](https://pywinauto.readthedocs.io/).
- pydirectinput-rgx: Direct Input 기반 Windows mouse/keyboard automation 후보입니다. GitHub 설명은 Windows에서 Direct Input을 사용하는 keyboard/mouse automation입니다. 이 프로젝트에서는 A/S/D/W 같은 control key live 실험 후보일 뿐, 한글/IME text 입력 baseline을 대체하지 않습니다. Source: [ReggX/pydirectinput_rgx](https://github.com/ReggX/pydirectinput_rgx).
- DXcam: Desktop Duplication API 기반 고속 capture 후보입니다. README는 low-latency, high-FPS capture pipeline과 full-screen Direct3D app 안정성을 목표로 설명합니다. 이 프로젝트에서는 monitor/ROI capture가 병목으로 확인될 때만 실험합니다. Source: [ra1nty/DXcam](https://github.com/ra1nty/DXcam).
- windows-capture: Windows Graphics Capture API / DXGI Desktop Duplication 계열 Rust+Python capture 후보입니다. README는 Rust와 Python용 Windows screen capture library이고 Graphics Capture API와 DXGI Desktop Duplication API 지원을 설명합니다. HWND/HMONITOR capture 실험 후보이지만 packaging/runtime 확인 전 baseline에 넣지 않습니다. Source: [NiiightmareXD/windows-capture](https://github.com/NiiightmareXD/windows-capture).

PM 판단: provider 후보는 모두 "없으면 어려운 문제가 확인될 때"만 승격합니다. 현재 reviewable baseline은 `mss`, builtin Win32 target state, `ctypes SendInput`, Hugging Face/OpenCV sensor 조합입니다.

## Dataset Candidates For Generalization

대용량 데이터셋 다운로드는 허용되었지만, 목적이 명확할 때만 사용합니다. 현재 ASDW baseline 검증에는 추가 대용량 다운로드가 필요하지 않습니다.

일반화 검증 후보:

- ScreenSpot / ScreenSpot-Pro: GUI grounding 평가용입니다. ScreenSpot-Pro는 professional high-resolution computer use GUI grounding 평가를 목적으로 합니다. Voxel51의 ScreenSpot-Pro dataset card는 1,581개 고해상도 screenshot, 23개 professional app, 5개 industry, 3개 OS, natural-language instruction과 bounding box annotation을 설명합니다. Sources: [ScreenSpot dataset](https://huggingface.co/datasets/rootsautomation/ScreenSpot), [ScreenSpot-Pro dataset](https://huggingface.co/datasets/Voxel51/ScreenSpot-Pro), [ScreenSpot-Pro blog](https://huggingface.co/blog/Ziyang/screenspot-pro).
- RICO: 모바일 UI screen과 UI hierarchy/semantic 정보를 갖는 데이터셋 계열입니다. 범용 UI 구조 이해나 모바일 UI 실험에 적합합니다. Sources: [RICO dataset](https://huggingface.co/datasets/creative-graphic-design/Rico), [Voxel51 RICO dataset](https://huggingface.co/datasets/Voxel51/rico), [RICO project page](https://interactionmining.org/rico).
- GroundCUA: desktop/web/mobile computer-use grounding과 UI perception 연구용 후보입니다. GroundCUA dataset card는 87개 software platform, screenshot/JSON annotation pair, UI element bbox/text/category 구조를 설명합니다. 현재 전체 agent training을 하려는 목적이 아니므로 대용량 action trajectory 학습에는 신중해야 합니다. Source: [GroundCUA dataset](https://huggingface.co/datasets/ServiceNow/GroundCUA).
- UI element detection datasets: web/mobile UI 요소 탐지 검증에 쓸 수 있습니다. Source: [YashJain UI Elements Detection Dataset](https://huggingface.co/datasets/YashJain/UI-Elements-Detection-Dataset).

현재 Hugging Face metadata readiness:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/gui_dataset_readiness.py"
```

결과는 `artifacts/gui-dataset-readiness/latest/report.md`에 저장됩니다. 2026-06-17 KST 기준 metadata inspection 결과:

| Dataset | Metadata Shape | Known Size | PM Use |
| --- | --- | ---: | --- |
| `Voxel51/ScreenSpot-Pro` | direct PNG + JSON | 3.384 GB | high-resolution external-box benchmark 후보 |
| `ServiceNow/GroundCUA` | direct PNG + JSON annotations | 21.614 GB | platform subset으로 bbox adapter 검토 |
| `YashJain/UI-Elements-Detection-Dataset` | direct PNG + JSON | 0.904 GB | 작은 UI element detection adapter 후보 |
| `rootsautomation/ScreenSpot` | parquet | 0.602 GB | parquet reader 승인 전 baseline 제외 |
| `rootsautomation/RICO-ScreenQA` | parquet | 3.325 GB | parquet reader 승인 전 baseline 제외 |

ScreenSpot-Pro tiny review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_screenspot_pro_tiny.py --max-samples 2"
```

결과는 `artifacts/screenspot-pro-tiny/latest/report.md`와 `overlays/`에 저장됩니다. 이 검증은 실제 ScreenSpot-Pro high-resolution GUI screenshot과 target bbox를 내려받아 `/grounding/review`와 `/predict`의 external box 경로에 넣습니다. 현재 ASDW classifier는 GUI element class를 예측하도록 학습된 모델이 아니므로, 이 결과는 "GUI grounding 정확도"가 아니라 "외부 GUI bbox provider를 퓨전 경계에 연결할 수 있는지"를 보는 staging evidence입니다.

UI-Elements tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_ui_elements_tiny.py --max-samples 2 --max-elements 12"
```

결과는 `artifacts/ui-elements-tiny/latest/report.md`와 `overlays/`에 저장됩니다. 이 검증은 `YashJain/UI-Elements-Detection-Dataset`의 작은 YOLO annotation subset을 외부 provider output처럼 다뤄 `/grounding/review`에 넣습니다. 2026-06-17 KST 실행에서는 두 web/UI sample의 14개 bbox가 모두 accepted 처리되었습니다. 이는 일반 GUI evidence boundary가 작동한다는 검증이며, YOLO provider 정확도나 실제 화면 자동화 성능 검증은 아닙니다.

GroundCUA tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_groundcua_tiny.py --max-samples 2 --max-elements 20"
```

결과는 `artifacts/groundcua-tiny/latest/report.md`와 `overlays/`에 저장됩니다. 이 검증은 `ServiceNow/GroundCUA`의 `data/<platform>/*.json` annotation을 외부 provider output처럼 다뤄 `/grounding/review`에 넣습니다. 2026-06-17 KST 실행에서는 OBS Studio와 Calibre desktop sample의 29개 bbox가 모두 accepted 처리되었습니다. 이는 desktop UI annotation evidence boundary가 작동한다는 검증이며, 실제 live 화면 provider 정확도나 task success 검증은 아닙니다.

Download rule:

- 목적이 "새 target UI에서 element localization 정확도 검증"이면 ScreenSpot 계열을 우선 검토합니다.
- 목적이 "mobile UI 구조 이해"이면 RICO 계열을 우선 검토합니다.
- 목적이 "full computer-use action grounding"이면 GroundCUA 같은 대형 데이터셋은 별도 실험 계획을 먼저 작성합니다.
- 새 데이터셋은 baseline 코드 경로를 더 무겁게 만들지 않는 검증 artifact로만 시작합니다.
- OmniParser 계열은 "일반 GUI element parsing"이 필요한 시나리오에서만 실험합니다. ASDW 버튼 분류 baseline을 대체하는 기본 의존성으로 승격하지 않습니다.

## Design Constraints

- 새 프로그램을 만들지 않습니다. 기존 `asdw_fusion.server`, Windows daemon, 기존 scripts를 사용합니다.
- 새로운 센서를 추가하더라도 입력 부서는 LLM보다 무거워지면 안 됩니다.
- live input은 별도 승인 없이는 검증하지 않습니다.
- 특정 실험 환경의 성능을 전체 일반화 성능으로 주장하지 않습니다.
