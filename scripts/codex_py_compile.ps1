$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = ".\.venv-win\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

& $Python -m py_compile `
    .\asdw_fusion\windows_capture_daemon.py `
    .\asdw_fusion\client_windows.py `
    .\asdw_fusion\server.py

Write-Host "Python compile check passed."

