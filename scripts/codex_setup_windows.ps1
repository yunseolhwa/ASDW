$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Python = ".\.venv-win\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Windows virtual environment is missing: .\.venv-win"
    Write-Host "Create it manually, then install requirements-windows.txt."
    exit 1
}

& $Python -m pip check
& powershell -ExecutionPolicy Bypass -File .\scripts\codex_py_compile.ps1

Write-Host "ASDW Windows setup check passed."

