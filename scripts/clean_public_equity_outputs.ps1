$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$targets = @(
    (Join-Path $RepoRoot "artifacts"),
    (Join-Path $RepoRoot "logs"),
    (Join-Path $RepoRoot "research\public_equity_theme_schema\visual_onboarding\dist")
)

foreach ($target in $targets) {
    $resolvedParent = Resolve-Path -LiteralPath (Split-Path -Parent $target) -ErrorAction SilentlyContinue
    if (-not $resolvedParent) {
        continue
    }

    $fullTarget = Join-Path $resolvedParent.Path (Split-Path -Leaf $target)
    if (-not $fullTarget.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean outside repository: $fullTarget"
    }

    if (Test-Path -LiteralPath $fullTarget) {
        Remove-Item -LiteralPath $fullTarget -Recurse -Force
        Write-Host "removed $fullTarget"
    }
}

Write-Host "Public equity generated outputs cleaned."
