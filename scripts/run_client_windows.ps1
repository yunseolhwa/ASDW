param(
    [switch]$LiveInput,
    [string]$Sensors = "template,classifier",
    [string]$RoiFrac = "0.34 0.46 0.66 0.57",
    [string]$DebugDir = ""
)

$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Project ".venv-win\Scripts\python.exe"

Set-Location $Project

if (-not (Test-Path $Python)) {
    throw "Windows virtual environment is missing: .\.venv-win. Run the Codex setup first."
}

$ArgsList = @(
    "-m", "asdw_fusion.client_windows",
    "--sensors", $Sensors,
    "--roi-frac"
) + $RoiFrac.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)

if ($LiveInput) {
    $ArgsList += "--live-input"
}
if ($DebugDir) {
    $ArgsList += @("--debug-dir", $DebugDir, "--draw-debug")
}

& $Python @ArgsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
