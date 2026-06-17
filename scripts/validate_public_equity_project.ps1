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

& $Python (Join-Path $SchemaRoot "tests\validate_schema.py")
& $Python (Join-Path $SchemaRoot "tests\validate_pm_database.py")

Write-Host "Public equity schema checks passed."
