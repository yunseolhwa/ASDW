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

## 구현된 provider API

기본 운영 경로는 계속 `builtin` 입력과 `mss` 캡처입니다. 강한 provider는 optional dependency로 두고 실패해도 데몬이 죽지 않게 구성했습니다.

- optional dependency 파일
  - `requirements-windows-strong.txt`
  - 포함: `pywinctl`, `pywinauto`, `pydirectinput-rgx`, `dxcam`
  - `windows-capture`는 주석 처리된 실험 후보
- `GET /providers`
  - window/input/capture/accessibility provider capability 반환
- target registry
  - `GET /targets`
  - `POST /targets/select`
  - `GET /targets/current`
  - `POST /targets/refresh`
  - PyWinCtl 우선, 실패 시 builtin Win32 fallback
- input provider
  - `POST /keys/press`에 `provider = builtin|pydirectinput`
  - dry-run은 provider 설치 여부와 무관하게 큐/타이밍만 검증
  - 한글/IME `type_text`는 builtin 유지
- capture provider
  - `/frame`, `/stream`, `/frame_base64`, `/predict_once`에 `provider = mss|dxcam|windows_capture`
  - `dxcam`은 ROI/target region 캡처 후보
  - `windows_capture`는 등록된 실험 후보이며 기본 실행 provider로는 아직 미연결
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
