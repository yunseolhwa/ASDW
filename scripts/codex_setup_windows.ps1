$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

$Python = Join-Path $ProjectRoot ".venv-win\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Windows virtual environment is missing: .\.venv-win"
    Write-Host "Creating it with scripts\setup_windows_client.ps1."
    Invoke-Checked "powershell" "-ExecutionPolicy" "Bypass" "-File" ".\scripts\setup_windows_client.ps1"
}

if (-not (Test-Path $Python)) {
    throw "Windows virtual environment was not created: .\.venv-win"
}

Invoke-Checked $Python "-m" "pip" "check"
Invoke-Checked "powershell" "-ExecutionPolicy" "Bypass" "-File" ".\scripts\codex_py_compile.ps1"

Write-Host "ASDW Windows setup check passed."

