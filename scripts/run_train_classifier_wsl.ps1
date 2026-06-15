param(
    [string]$Distro = "Ubuntu-24.04-ROCmLab",
    [int]$Epochs = 12,
    [int]$BatchSize = 48
)

$WslProject = "/mnt/d/asdw-fusion-typer"
wsl -d $Distro -- bash -lc "cd '$WslProject' && source .venv-wsl/bin/activate && export HSA_ENABLE_SDMA=0 HSA_OVERRIDE_GFX_VERSION=10.3.0 && python scripts/generate_asdw_classifier_data.py && python scripts/train_asdw_classifier.py --epochs '$Epochs' --batch-size '$BatchSize'"
