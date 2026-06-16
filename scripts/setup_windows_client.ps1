param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $Project ".venv-win"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Requirements = Join-Path $Project "requirements-windows.txt"

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

Set-Location $Project

if (-not $PythonPath) {
    $Candidates = @(
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
        "python",
        "py"
    )
    foreach ($Candidate in $Candidates) {
        try {
            & $Candidate --version *> $null
            if ($LASTEXITCODE -eq 0) {
                $PythonPath = $Candidate
                break
            }
        } catch {
        }
    }
}

if (-not $PythonPath) {
    throw "No Python executable found. Pass -PythonPath explicitly."
}

if (-not (Test-Path $VenvPython)) {
    Invoke-Checked $PythonPath "-m" "venv" $VenvDir
}

Invoke-Checked $VenvPython "-m" "pip" "install" "--upgrade" "pip==26.1.2" "wheel==0.47.0" "setuptools==82.0.1"
Invoke-Checked $VenvPython "-m" "pip" "install" "-r" $Requirements
