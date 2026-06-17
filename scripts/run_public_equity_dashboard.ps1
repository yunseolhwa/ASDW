param(
    [int] $Port = 5173,
    [switch] $SkipInstall
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppRoot = Join-Path $RepoRoot "research\public_equity_theme_schema\visual_onboarding"

function Resolve-Npm {
    $command = Get-Command "npm" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "npm was not found on PATH. Install Node.js/npm before running the visual onboarding dashboard."
}

& (Join-Path $PSScriptRoot "build_public_equity_database.ps1")

$Npm = Resolve-Npm

Push-Location $AppRoot
try {
    if (-not $SkipInstall -and -not (Test-Path (Join-Path $AppRoot "node_modules"))) {
        & $Npm install
    }

    & $Npm run dev -- --host 127.0.0.1 --port $Port
}
finally {
    Pop-Location
}
