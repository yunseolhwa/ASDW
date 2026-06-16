# Fusion Module Review State

Last updated: 2026-06-17 KST

## Reviewable Surface

현재 검토 가능한 endpoint:

- `GET /health`: 서버, device, cv2, poller, heartbeat 상태.
- `GET /fusion/status`: baseline/candidate 센서 목록, 역할, 현재 로드된 센서, 가중치, 모델 경로.
- `POST /predict`: 이미지 base64 + sensor list를 받아 detections, sensor votes, fused scores, fusion review summary 반환. optional `boxes`를 넣으면 외부 box proposal을 사용합니다.
- `POST /grounding/review`: 외부 GUI element bbox/text/label을 받아 정규화 좌표, crop 요약, instruction overlap, rejected box를 반환합니다.
- `POST /agent/step`: capture 또는 inline image + vision + `auto|llm|vision_rule` controller 판단까지 수행하며 입력하지 않음.
- `POST /agent/act`: 모드 정책을 통과한 action만 daemon에 전달.

현재 검토 가능한 artifact:

- `artifacts/fusion-review-bundle/latest/report.md`
- `artifacts/fusion-review-bundle/latest/report.json`
- `artifacts/fusion-readiness-audit/latest/report.md`
- `artifacts/fusion-readiness-audit/latest/report.json`
- `artifacts/visual-checks/detection-bboxes-clean.png`
- `artifacts/visual-checks/detection-bboxes.png`
- `artifacts/fusion-review/latest/report.md`
- `artifacts/fusion-review/latest/report.json`
- `artifacts/fusion-review/latest-label-boxes/report.md`
- `artifacts/fusion-review/latest-builtin-detector/report.md`
- `artifacts/fusion-contract/latest/report.md`
- `artifacts/fusion-contract/latest/report.json`
- `artifacts/agent-policy-smoke/latest/report.md`
- `artifacts/agent-policy-smoke/latest/report.json`
- `artifacts/agent-step-inline-smoke/latest/report.md`
- `artifacts/agent-step-inline-smoke/latest/report.json`
- `artifacts/gpu-server-smoke/latest/report.md`
- `artifacts/gpu-server-smoke/latest/report.json`
- `artifacts/gui-dataset-readiness/latest/report.md`
- `artifacts/gui-dataset-readiness/latest/report.json`
- `artifacts/screenspot-pro-tiny/latest/report.md`
- `artifacts/screenspot-pro-tiny/latest/report.json`
- `artifacts/screenspot-pro-tiny/latest/overlays/`
- `artifacts/ui-elements-tiny/latest/report.md`
- `artifacts/ui-elements-tiny/latest/report.json`
- `artifacts/ui-elements-tiny/latest/overlays/`
- `artifacts/groundcua-tiny/latest/report.md`
- `artifacts/groundcua-tiny/latest/report.json`
- `artifacts/groundcua-tiny/latest/overlays/`
- `models/asdw-mobilenetv3-classifier/best`
- `models/asdw-mobilenetv3-classifier/best/asdw_training_metadata.json`

## Verified Results

Review bundle:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\build_fusion_review_bundle.py
```

최근 결과: `reviewable_with_known_gaps`.

| Gate | Status | Evidence |
| --- | --- | --- |
| contract safety gates | `pass` | `21/21` |
| agent observe/rehearse policy | `pass` | `4/4`, direct `/agent/act` decisions, no LLM, no live input |
| inline /agent/step vision_rule | `pass` | inline image -> vision -> `press_sequence`, sequence `SDWWDWDAA`, warm latency about `150 ms` |
| baseline ASDW fusion sample | `pass` | `template,classifier` expected sequence match |
| external-box synthetic dataset | `pass` | label boxes, `19/20` sequence accuracy |
| external GUI evidence plumbing | `pass` | ScreenSpot-Pro `2`, UI-Elements `14`, GroundCUA `29` accepted boxes |
| live input | `not_run` | intentionally not executed |
| WSL ROCm GPU server smoke | `pass` | temporary server, `prediction.device == cuda`, sequence `SDWWDWDAA` |
| SGLang runtime | `offline` | local `/v1/models` connection timeout |

Readiness audit:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\audit_fusion_readiness.py
```

최근 결과: `reviewable`, `31/31` checks passed. 이 audit는 구현이 "사람 검토 가능한 상태"인지 확인합니다. live 입력, SGLang runtime, optional provider, 장시간 soak를 완료 조건으로 둔 것이 아니라, 해당 항목들이 명시적으로 미검증으로 분리되어 있는지까지 확인합니다.

검증 이미지: `artifacts/visual-checks/detection-bboxes-clean.png`

| Sensors | Result | Detections | Notes |
| --- | --- | ---: | --- |
| `template` | `AASSAAAA` | 9 | raw sensor sequence는 `AASSAWAAA`; 1개가 confidence 기준 아래라 제외 |
| `classifier` | `SDWWDWDAA` | 9 | 첫 모델 로드는 수십 초 걸릴 수 있고, 이후 정답 |
| `template,classifier` | `SDWWDWDAA` | 9 | warm 상태 약 0.10-0.18초; agreement rate `0.3333` |

최근 `POST /predict` 검토 요약:

- `fusion.sensor_sequences.template`: `AASSAWAAA`
- `fusion.sensor_sequences.classifier`: `SDWWDWDAA`
- `fusion.accepted_count`: `9`
- `fusion.rejected_count`: `0`
- `fusion.disagreements`: `6`
- 각 detection은 `sensor_keys`와 `fused_scores`를 포함합니다.

후보 센서 runtime smoke:

| Sensor | Runtime | Result | Notes |
| --- | ---: | --- | --- |
| `clip` | 약 1.0-1.5초 | `SDWWSWDAA` | 호출 가능. 샘플에서 1개 오답이라 baseline 아님 |
| `trocr` | 약 1.5-1.9초 | accepted sequence 없음 | raw sensor sequence `AAAAAAAAA`; 현재 샘플에는 부적합 |
| `owlvit` | 약 0.50초 | accepted sequence 없음 | Transformers API fallback 적용 후 500 없이 응답. raw sensor sequence `?????????` |

Report 생성 명령:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\review_fusion_server.py --include-candidates
```

Dataset 비교 report:

| Route | Samples | Sequence Accuracy | Detection Count | Evidence |
| --- | ---: | ---: | ---: | --- |
| built-in detector | 20 | `0/20` | `0/20` | `artifacts/fusion-review/latest-builtin-detector/report.md` |
| label boxes as external proposals | 20 | `19/20` | `20/20` | `artifacts/fusion-review/latest-label-boxes/report.md` |

해석: 현재 ASDW classifier/fusion은 box proposal이 주어질 때 강합니다. 반대로 built-in detector는 중앙 한 줄 prompt를 전제로 하므로 타일형 synthetic layout에는 맞지 않습니다. 범용 GUI 확장은 classifier 재학습보다 box proposal provider가 다음 병목입니다.

계약 검증 report:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/verify_fusion_contracts.py"
```

최근 결과: `21/21` pass. 검증 범위는 LLM action schema, invalid key/action rejection, low-confidence blocking, blocked/error state blocking, empty prediction blocking, `vision_rule` controller decision, observe/live mode policy, external `boxes` normalization, generic grounding evidence schema, classifier-weighted fusion, baseline/candidate sensor separation입니다. 이 검증은 daemon endpoint, model loading, SGLang을 호출하지 않습니다.

Agent policy HTTP smoke:

```powershell
.\.venv-win\Scripts\python.exe .\scripts\smoke_agent_policy.py
```

최근 결과: `4/4` pass. 검증 범위는 direct `/agent/act` decision에서 `observe` 입력 skip, `rehearse` daemon `dry_run=true`, `live` without `allow_live_input` 차단, low-confidence 차단입니다. 이 검증은 capture, LLM call, live input을 수행하지 않습니다.

WSL ROCm GPU server smoke:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/smoke_server_wsl_gpu.py --port 7869 --startup-timeout-sec 120 --predict-timeout-sec 180"
```

최근 결과: `4/4` pass. 임시 서버 시작 직후 `/fusion/status`는 모델 미로드 상태라 `device=cpu`였고, `/predict` 호출 후 classifier가 로드되면서 `prediction.device=cuda`, post-predict status `device=cuda`, sequence `SDWWDWDAA`를 확인했습니다. 첫 로드 포함 latency는 약 `44.2s`입니다. 이 검증은 입력 endpoint를 호출하지 않으며, 장시간 안정성 검증도 아닙니다.

GUI dataset readiness report:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/gui_dataset_readiness.py"
```

최근 결과:

| Dataset | Readiness | Known Size |
| --- | --- | ---: |
| `Voxel51/ScreenSpot-Pro` | `metadata_ready_large_benchmark` | 3.384 GB |
| `ServiceNow/GroundCUA` | `metadata_ready_large_direct_files` | 21.614 GB |
| `YashJain/UI-Elements-Detection-Dataset` | `metadata_ready_direct_image_json` | 0.904 GB |
| `rootsautomation/ScreenSpot` | `metadata_ready_requires_parquet_reader` | 0.602 GB |
| `rootsautomation/RICO-ScreenQA` | `metadata_ready_requires_parquet_reader` | 3.325 GB |

해석: metadata readiness는 대용량 다운로드 전에 파일 구조와 크기만 확인하는 단계입니다. 실제 tiny sample flow 검증은 아래 ScreenSpot-Pro와 UI-Elements report로 분리합니다.

ScreenSpot-Pro tiny review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_screenspot_pro_tiny.py --max-samples 2"
```

최근 결과:

| UI ID | App | Platform | Instruction | Grounding | Evidence |
| --- | --- | --- | --- | --- | --- |
| `eviews_windows_10` | EViews | Windows | capture tab | `/grounding/review` accepted 1 bbox, area ratio `0.00053048` | `artifacts/screenspot-pro-tiny/latest/overlays/01-screenshot_2024-12-05_21-43-26.png` |
| `eviews_windows_14` | EViews | Windows | open the edit button | `/grounding/review` accepted 1 bbox, area ratio `0.00011092` | `artifacts/screenspot-pro-tiny/latest/overlays/02-screenshot_2024-12-05_21-38-20.png` |

해석: 실제 high-resolution professional GUI benchmark의 bbox가 `/grounding/review`와 `/predict` external box 경계로 들어가고 reviewable overlay/report가 생성됩니다. 현재 A/S/D/W output은 out-of-domain evidence이며 GUI grounding accuracy로 주장하지 않습니다.

UI-Elements tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_ui_elements_tiny.py --max-samples 2 --max-elements 12"
```

최근 결과:

| Sample | Elements | Accepted | Classes | Evidence |
| --- | ---: | ---: | --- | --- |
| `mostvisited_telegra.ph_1729630961` | 12 | 12 | `button:11`, `input:1` | `artifacts/ui-elements-tiny/latest/overlays/train-mostvisited_telegra.ph_1729630961.png` |
| `mostvisited_secureserver.net_1729631319` | 2 | 2 | `button:2` | `artifacts/ui-elements-tiny/latest/overlays/train-mostvisited_secureserver.net_1729631319.png` |

해석: YOLO annotation을 외부 provider output처럼 다뤄 `/grounding/review`가 일반 web/UI element bbox를 정규화하고 crop evidence로 남기는지 확인했습니다. 이 스크립트는 `/predict`나 입력 endpoint를 호출하지 않습니다. provider 정확도 검증은 아닙니다.

GroundCUA tiny grounding review:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && .venv-wsl/bin/python scripts/review_groundcua_tiny.py --max-samples 2 --max-elements 20"
```

최근 결과:

| Platform | Elements | Accepted | Categories | Evidence |
| --- | ---: | ---: | --- | --- |
| `OBS Studio` | 20 | 20 | `unknown:20` | `artifacts/groundcua-tiny/latest/overlays/OBS_Studio-294cbb130c812388c30abd3b97cf7b7872c139d47d6847ff8126246e219af900.png` |
| `Calibre` | 9 | 9 | `unknown:6`, `Others:3` | `artifacts/groundcua-tiny/latest/overlays/Calibre-9a7b75e6484b869d9847c989c0e6ada49114cdd65b9bcc70e8742173f7fea382.png` |

해석: GroundCUA desktop annotation을 외부 provider output처럼 다뤄 `/grounding/review`가 bbox를 정규화하고 crop evidence로 남기는지 확인했습니다. 이 스크립트는 `/predict`나 입력 endpoint를 호출하지 않습니다. 실제 화면 provider 정확도나 task success 검증은 아닙니다.

학습 artifact:

- `best_val_acc`: `1.0`
- labels: `A`, `S`, `D`, `W`
- device: `cuda`
- gpu: `AMD Radeon RX 6600 XT`

## Known Runtime Notes

- 현재 7868 서버는 최신 `/fusion/status`를 제공합니다.
- 현재 백그라운드 리뷰 서버는 classifier device가 CPU로 잡힐 수 있습니다. 정확도 검토는 가능하지만 GPU 상태 판단은 `artifacts/gpu-server-smoke/latest/report.md`를 기준으로 봅니다.
- GPU smoke는 ROCm runtime flags인 `HSA_ENABLE_SDMA=0`, `HSA_OVERRIDE_GFX_VERSION=10.3.0`를 설정한 임시 서버에서 통과했습니다. 첫 classifier 로드 포함 `/predict` latency는 약 `44.2s`였습니다.
- 직접 ad-hoc Python으로 classifier를 로드한 한 번의 시도는 ROCm SDMA assertion으로 실패했습니다. 서버 실행 스크립트의 ROCm flags가 없는 검증은 신뢰하지 않습니다.
- WSL 직접 ROCm probe는 `torch.cuda.is_available() == true`와 `AMD Radeon RX 6600 XT`를 확인했습니다.

## Not Verified Yet

- live input: `live + allow_live_input=true`
- CLIP/TrOCR/OWL-ViT의 다른 GUI/앱/게임 화면 일반화 성능
- external box provider의 실제 GUI 화면 성능
- SGLang runtime version and live `/llm/check`
- long-running daemon soak test
- long-running GPU server soak test and warm-latency distribution
- external GUI grounding accuracy on ScreenSpot/RICO/GroundCUA; ScreenSpot-Pro, UI-Elements, GroundCUA tiny external-box/review flow만 확인됨

## PM Readout

현재 퓨전 모듈은 "작은 센서 조합" 방향으로 작동합니다. `template`은 빠른 기준 센서이고, `classifier`는 현재 정확도를 책임지는 센서입니다. `template,classifier` 조합은 warm 상태에서 1초 미만으로 정답을 반환했습니다.

다음 검토 포인트는 일반화입니다. 초기 실험 화면을 벗어나려면 ScreenSpot/RICO/GroundCUA 같은 GUI 데이터셋으로 element localization 또는 prompt reading을 검증해야 합니다. 다만 이 단계는 baseline 입력 경계를 무겁게 하지 않는 별도 검증으로 다뤄야 합니다.
