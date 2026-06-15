param(
    [switch]$LiveInput,
    [string]$Sensors = "template,classifier",
    [string]$RoiFrac = "0.34 0.46 0.66 0.57",
    [string]$DebugDir = ""
)

$Project = "D:\asdw-fusion-typer"
$ArgsList = @(
    "-m", "asdw_fusion.client_windows",
    "--sensors", $Sensors,
    "--roi-frac"
) + $RoiFrac.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)

if ($LiveInput) {
    $ArgsList += "--live-input"
}
if ($DebugDir) {
    $ArgsList += @("--debug-dir", $DebugDir, "--draw-debug")
}

& "$Project\.venv-win\Scripts\python.exe" @ArgsList
