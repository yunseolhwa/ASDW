# TODO: Local Daemon and LLM Controller

이 문서는 현재 Windows 캡처 데몬을 수동 운영 상태로 두고, 나중에 로컬 LLM 모델이 들어왔을 때 상태체크/상태머신 로직을 붙이기 위한 작업 목록입니다.

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

## 나중에 붙일 로컬 LLM 역할

LLM은 비전 분류기가 아니라 상태 컨트롤러입니다.

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

## 데몬에 추가할 상태체크 로직

로컬 LLM이 들어오면 Windows 캡처 데몬 또는 상위 orchestrator에 다음 상태체크를 추가합니다.

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

- `GET /daemon/status`
  - 캡처 데몬, 비전 서버, LLM 서버 상태를 한 번에 반환
- `POST /agent/step`
  - 전체 화면 캡처
  - 비전 추론
  - 상태 업데이트
  - LLM 판단
  - 액션 JSON 반환
- `POST /agent/act`
  - `agent/step` 결과를 실제 키 입력까지 실행
  - 기본은 dry-run
- `POST /llm/check`
  - 로컬 LLM endpoint 상태 확인
- `POST /config`
  - LLM base URL, 모델명, FPS, JPEG 품질, dry-run 설정 변경
- `GET /config`
  - 현재 설정 조회

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
2. 비전 서버와 캡처 데몬을 안정화
3. LLM 서버가 정해지면 `/llm/check` 추가
4. deterministic FSM 먼저 작성
5. 애매한 상태에서만 LLM 호출
6. `agent/step`과 `agent/act` 분리

## 주의

- 매 프레임 LLM을 호출하지 않습니다.
- 키 입력 루프는 deterministic rule이 우선입니다.
- LLM은 판단이 애매한 순간의 advisor로 둡니다.
- 로컬 모델만 사용합니다.
- 외부 API 의존성을 운영 경로에 넣지 않습니다.
