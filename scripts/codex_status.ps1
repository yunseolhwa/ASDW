$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "== Git =="
git status --short --branch
git remote -v

Write-Host ""
Write-Host "== Windows daemon =="
try {
    Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:7870/ping" -TimeoutSec 2 | ConvertTo-Json -Depth 8
} catch {
    Write-Host "Daemon offline or not reachable: http://127.0.0.1:7870"
}

Write-Host ""
Write-Host "== WSL model server =="
try {
    Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:7868/health" -TimeoutSec 2 | ConvertTo-Json -Depth 8
} catch {
    Write-Host "Model server offline or not reachable: http://127.0.0.1:7868"
}

