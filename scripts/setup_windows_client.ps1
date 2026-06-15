param(
    [string]$PythonPath = ""
)

$Project = "D:\asdw-fusion-typer"
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

& $PythonPath -m venv "$Project\.venv-win"
& "$Project\.venv-win\Scripts\python.exe" -m pip install --upgrade pip==26.1.2 wheel==0.47.0 setuptools==82.0.1
& "$Project\.venv-win\Scripts\python.exe" -m pip install -r "$Project\requirements-windows.txt"
