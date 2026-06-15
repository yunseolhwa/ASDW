$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "== ASDW cleanup =="

$TempTargets = @(
    (Join-Path $env:TEMP "codex-asar-tools"),
    (Join-Path $env:TEMP "codex-asar-extract")
)

foreach ($Target in $TempTargets) {
    if (Test-Path $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
        Write-Host "Removed temp: $Target"
    }
}

$ProjectTargets = @(
    ".pytest_cache",
    "debug",
    "artifacts\tmp"
)

foreach ($RelativePath in $ProjectTargets) {
    $Target = Join-Path $ProjectRoot $RelativePath
    if (Test-Path $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
        Write-Host "Removed project temp: $RelativePath"
    }
}

$CacheRoots = @(
    "asdw_fusion",
    "scripts"
)

foreach ($RelativePath in $CacheRoots) {
    $Root = Join-Path $ProjectRoot $RelativePath
    if (-not (Test-Path $Root)) {
        continue
    }

    Get-ChildItem -Path $Root -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
            Write-Host "Removed Python cache: $($_.FullName.Substring($ProjectRoot.Length + 1))"
        }
}

Write-Host "Cleanup complete."
