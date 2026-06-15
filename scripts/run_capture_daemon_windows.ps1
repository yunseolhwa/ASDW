param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 7870
)

$Project = "D:\asdw-fusion-typer"
$Python = "$Project\.venv-win\Scripts\python.exe"

& $Python -m uvicorn asdw_fusion.windows_capture_daemon:app --host $HostAddress --port $Port
