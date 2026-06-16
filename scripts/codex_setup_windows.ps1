$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$WorktreePython = Join-Path $ProjectRoot ".venv-win\Scripts\python.exe"
$PinnedPython = "D:\asdw-fusion-typer\.venv-win\Scripts\python.exe"

if (Test-Path -LiteralPath $WorktreePython) {
    $Python = $WorktreePython
} elseif (Test-Path -LiteralPath $PinnedPython) {
    $Python = $PinnedPython
} else {
    Write-Host "Windows virtual environment is missing."
    Write-Host "Checked:"
    Write-Host "  $WorktreePython"
    Write-Host "  $PinnedPython"
    Write-Host "Create it with: powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows_client.ps1"
    exit 1
}

& $Python -m pip check
& $Python -m py_compile `
    .\asdw_fusion\windows_capture_daemon.py `
    .\asdw_fusion\client_windows.py `
    .\asdw_fusion\server.py

Write-Host "ASDW Windows setup check passed."

