param(
    [string]$Distro = "Ubuntu-24.04-ROCmLab",
    [string]$Sensors = "template,classifier",
    [int]$Port = 7868
)

$ErrorActionPreference = "Stop"

$Project = Split-Path -Parent $PSScriptRoot
$WslPathInput = $Project -replace "\\", "/"
$WslProject = (& wsl -d $Distro -- wslpath -a $WslPathInput).Trim()
if ($LASTEXITCODE -ne 0 -or -not $WslProject) {
    throw "Failed to convert project path for WSL: $Project"
}

$Command = "cd '$WslProject' && source .venv-wsl/bin/activate && export HSA_ENABLE_SDMA=0 HSA_OVERRIDE_GFX_VERSION=10.3.0 ASDW_SENSORS='$Sensors' ASDW_PORT='$Port' && python -m asdw_fusion.server"

wsl -d $Distro -- bash -lc $Command
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
