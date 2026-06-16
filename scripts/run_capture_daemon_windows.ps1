param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 7870
)

$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project ".venv-win\Scripts\python.exe"

Set-Location $Project

if (-not (Test-Path $Python)) {
    throw "Windows virtual environment is missing: .\.venv-win. Run the Codex setup first."
}

& $Python -m uvicorn asdw_fusion.windows_capture_daemon:app --host $HostAddress --port $Port
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
