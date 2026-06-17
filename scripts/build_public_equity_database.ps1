param(
    [switch] $CoreOnly
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SchemaRoot = Join-Path $RepoRoot "research\public_equity_theme_schema"

function Resolve-PublicEquityPython {
    $candidates = @(
        (Join-Path $RepoRoot ".venv-win\Scripts\python.exe"),
        "C:\Users\ROCmAdmin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
        "python"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -like "*\*") {
            if (Test-Path $candidate) {
                return $candidate
            }
            continue
        }

        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }

    throw "No Python runtime found. Expected .venv-win or Codex bundled Python."
}

$Python = Resolve-PublicEquityPython
$buildArgs = @("--force")
if ($CoreOnly) {
    $buildArgs += "--core-only"
}

& $Python (Join-Path $SchemaRoot "build_theme_database.py") @buildArgs
& $Python (Join-Path $SchemaRoot "visual_onboarding\export_dashboard_data.py")

Write-Host "Public equity database and dashboard data generated."
