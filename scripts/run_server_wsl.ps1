param(
    [string]$Distro = "Ubuntu-24.04-ROCmLab",
    [string]$Sensors = "template,classifier",
    [int]$Port = 7868
)

$Project = "D:\asdw-fusion-typer"
$WslProject = "/mnt/d/asdw-fusion-typer"

wsl -d $Distro -- bash -lc "cd '$WslProject' && source .venv-wsl/bin/activate && export HSA_ENABLE_SDMA=0 HSA_OVERRIDE_GFX_VERSION=10.3.0 ASDW_SENSORS='$Sensors' ASDW_PORT='$Port' && python -m asdw_fusion.server"
