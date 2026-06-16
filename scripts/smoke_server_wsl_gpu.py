from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_OUTPUT_DIR = Path("artifacts/gpu-server-smoke/latest")
DEFAULT_IMAGE = Path("artifacts/visual-checks/detection-bboxes-clean.png")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start a temporary WSL/ROCm server and verify GPU-backed /predict without daemon input.",
    )
    parser.add_argument("--port", type=int, default=7869)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--expected-sequence", default="SDWWDWDAA")
    parser.add_argument("--startup-timeout-sec", type=float, default=90.0)
    parser.add_argument("--predict-timeout-sec", type=float, default=90.0)
    return parser.parse_args()


def wait_for_status(base_url: str, timeout_sec: float) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_error = None
    while time.time() < deadline:
        try:
            response = requests.get(f"{base_url}/fusion/status", timeout=2.0)
            if response.ok:
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(1.0)
    raise TimeoutError(f"server did not answer /fusion/status: {last_error}")


def post_predict(base_url: str, image_path: Path, timeout_sec: float) -> dict[str, Any]:
    payload = {
        "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        "sensors": ["template", "classifier"],
        "debug": True,
    }
    response = requests.post(f"{base_url}/predict", json=payload, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def start_server(port: int) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "HSA_ENABLE_SDMA": "0",
            "HSA_OVERRIDE_GFX_VERSION": "10.3.0",
            "ASDW_SENSORS": "template,classifier",
            "ASDW_PORT": str(port),
        }
    )
    command = [sys.executable, "-m", "asdw_fusion.server"]
    return subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def stop_server(process: subprocess.Popen[str]) -> dict[str, Any]:
    if process.poll() is None:
        if os.name == "nt":
            process.terminate()
        else:
            process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
    stdout, stderr = process.communicate(timeout=5)
    return {
        "returncode": process.returncode,
        "stdout_tail": tail_text(stdout),
        "stderr_tail": tail_text(stderr),
    }


def tail_text(value: str, max_lines: int = 80) -> str:
    lines = value.splitlines()
    return "\n".join(lines[-max_lines:])


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# GPU Server Smoke",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Status: `{report['status']}`",
        f"- Port: `{report['port']}`",
        "- Scope: temporary server process only; no daemon input endpoint is called.",
        "",
        "## Checks",
        "",
        "| Check | Result | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {escape_md(check['name'])} | `{check['status']}` | {escape_md(check.get('evidence'))} |"
        )
    lines.extend(
        [
            "",
            "## Runtime",
            "",
            f"- Pre-predict status: `{json.dumps(report.get('pre_status'), ensure_ascii=False)}`",
            f"- Post-predict status: `{json.dumps(report.get('post_status'), ensure_ascii=False)}`",
            f"- Prediction: `{json.dumps(report.get('prediction_summary'), ensure_ascii=False)}`",
            "",
            "## Process Tail",
            "",
            "```text",
            str((report.get("process") or {}).get("stderr_tail") or (report.get("process") or {}).get("stdout_tail") or ""),
            "```",
        ]
    )
    return "\n".join(lines) + "\n"


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = f"http://127.0.0.1:{args.port}"
    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()

    checks: list[dict[str, Any]] = []
    pre_status: dict[str, Any] | None = None
    post_status: dict[str, Any] | None = None
    prediction: dict[str, Any] | None = None
    process_info: dict[str, Any] | None = None
    error: str | None = None

    process = start_server(args.port)
    try:
        pre_status = wait_for_status(base_url, args.startup_timeout_sec)
        checks.append(
            {
                "name": "temporary server answers status",
                "status": "pass",
                "evidence": f"pre_predict_device={pre_status.get('device')}",
            }
        )
        prediction = post_predict(base_url, args.image.resolve(), args.predict_timeout_sec)
        prediction_device = prediction.get("device")
        checks.append(
            {
                "name": "predict reports GPU device",
                "status": "pass" if prediction_device == "cuda" else "fail",
                "evidence": f"prediction_device={prediction_device}",
            }
        )
        sequence_text = prediction.get("sequence_text")
        checks.append(
            {
                "name": "template,classifier predict matches sample",
                "status": "pass" if sequence_text == args.expected_sequence else "fail",
                "evidence": f"sequence={sequence_text}, expected={args.expected_sequence}, device={prediction.get('device')}",
            }
        )
        post_status = wait_for_status(base_url, 5.0)
        post_device = post_status.get("device")
        checks.append(
            {
                "name": "post-predict status reports GPU device",
                "status": "pass" if post_device == "cuda" else "note",
                "evidence": f"post_predict_device={post_device}",
            }
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        checks.append({"name": "gpu server smoke exception", "status": "fail", "evidence": error})
    finally:
        process_info = stop_server(process)

    status = "fail" if any(item["status"] == "fail" for item in checks) else "pass"
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "status": status,
        "port": args.port,
        "pre_status": pre_status,
        "post_status": post_status,
        "prediction_summary": summarize_prediction(prediction),
        "checks": checks,
        "error": error,
        "process": process_info,
    }
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{status}: {sum(1 for item in checks if item['status'] == 'pass')}/{len(checks)} checks passed")
    return 0 if status == "pass" else 1


def summarize_prediction(prediction: dict[str, Any] | None) -> dict[str, Any] | None:
    if prediction is None:
        return None
    return {
        "sequence_text": prediction.get("sequence_text"),
        "detections": len(prediction.get("detections") or []),
        "latency_ms": prediction.get("latency_ms"),
        "device": prediction.get("device"),
        "box_source": prediction.get("box_source"),
        "fusion": prediction.get("fusion"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
