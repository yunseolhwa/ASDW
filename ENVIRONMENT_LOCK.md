# ASDW Fusion Typer Environment Lock

Last verified: 2026-06-16 KST

This project uses two local runtimes:

- Windows daemon runtime: screen capture, `SendInput` keyboard injection, queue handling.
- WSL ROCm runtime: vision server, model inference, heartbeat polling.

## Windows Runtime

Host:

```text
OS: Microsoft Windows 11 IoT Enterprise LTSC
Version: 10.0.26100
Build: 26100
Architecture: 64-bit
PowerShell: 7.6.2
Python: 3.12.13
Virtualenv: D:\asdw-fusion-typer\.venv-win
```

Pinned installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows_client.ps1
```

Pinned direct dependencies live in `requirements-windows.txt`.

Tooling versions are pinned by `scripts/setup_windows_client.ps1`:

```text
pip==26.1.2
wheel==0.47.0
setuptools==82.0.1
```

### SendInput ABI Lock

The Windows daemon uses `ctypes` with the 64-bit Windows `INPUT` layout. The expected sizes are:

```text
ctypes.c_void_p: 8
KEYBDINPUT: 24
MOUSEINPUT: 32
INPUT: 40
```

If `SendInput` returns `[WinError 87] The parameter is incorrect`, check these sizes first:

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

## WSL ROCm Runtime

Host:

```text
Distro: Ubuntu-24.04-ROCmLab
OS: Ubuntu 24.04 LTS (Noble Numbat)
Kernel: 6.18.33.1-microsoft-standard-WSL2
Python: 3.12.3
Virtualenv: /mnt/d/asdw-fusion-typer/.venv-wsl
GPU: AMD Radeon RX 6600 XT
PyTorch: 2.11.0+rocm7.2
TorchVision: 0.26.0+rocm7.2
TorchAudio: 2.11.0+rocm7.2
Triton ROCm: 3.6.0
```

Pinned installer:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && bash scripts/setup_wsl_rocm.sh"
```

Pinned direct dependencies live in `requirements-wsl-rocm.txt`.

Tooling versions are pinned by `scripts/setup_wsl_rocm.sh`:

```text
pip==26.1.2
wheel==0.47.0
setuptools==70.2.0
```

ROCm runtime flags used by `scripts/run_server_wsl.ps1`:

```text
HSA_ENABLE_SDMA=0
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

## Verification Commands

Windows syntax and daemon ABI:

```powershell
.\.venv-win\Scripts\python.exe -m py_compile .\asdw_fusion\windows_capture_daemon.py .\asdw_fusion\server.py
.\.venv-win\Scripts\python.exe -c "import ctypes; from asdw_fusion.windows_capture_daemon import INPUT, KEYBDINPUT, MOUSEINPUT; print(ctypes.sizeof(ctypes.c_void_p), ctypes.sizeof(KEYBDINPUT), ctypes.sizeof(MOUSEINPUT), ctypes.sizeof(INPUT))"
```

WSL syntax and ROCm:

```powershell
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && source .venv-wsl/bin/activate && python -m py_compile asdw_fusion/server.py asdw_fusion/windows_capture_daemon.py"
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && source .venv-wsl/bin/activate && python - <<'PY'
import torch
print(torch.__version__)
print(torch.cuda.is_available())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no gpu')
PY"
```

Dependency drift check:

```powershell
.\.venv-win\Scripts\python.exe -m pip freeze
wsl -d Ubuntu-24.04-ROCmLab -- bash -lc "cd /mnt/d/asdw-fusion-typer && source .venv-wsl/bin/activate && python -m pip freeze"
```

## Operational Daemon Lock Status

Development/runtime versions are pinned in this file and in the requirements files. The Windows daemon is not yet locked as an operating-system service.

Remaining operational lock items are tracked in `TODO-local-daemon-and-llm.md`:

- Windows Service registration
- administrator privilege policy
- automatic start and restart policy
- fixed log path and rotation
- fixed service host/port/options
- update and rollback procedure
- heartbeat-based restart/alert policy
