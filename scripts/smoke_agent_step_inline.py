from __future__ import annotations

import argparse
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_IMAGE = Path("artifacts/visual-checks/detection-bboxes-clean.png")
DEFAULT_FUSION_REPORT = Path("artifacts/fusion-review/latest/report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/agent-step-inline-smoke/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test /agent/step with an inline image and the local vision_rule controller.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument("--expected-sequence", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument("--min-action-confidence", type=float, default=0.60)
    return parser.parse_args()


def image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def expected_sequence(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if not DEFAULT_FUSION_REPORT.exists():
        return None
    try:
        data = json.loads(DEFAULT_FUSION_REPORT.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = data.get("expected_sequence")
    return str(value) if value else None


def post_agent_step(server: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    response = requests.post(f"{server.rstrip('/')}/agent/step", json=payload, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def classify_response(response: dict[str, Any], expected: str | None) -> str:
    frame = response.get("frame") or {}
    controller = response.get("controller") or {}
    decision = response.get("decision") or {}
    keys = "".join(decision.get("keys") or [])
    if response.get("ok") is not True:
        return "review"
    if frame.get("provider") != "inline_image":
        return "review"
    if controller.get("selected") != "vision_rule":
        return "review"
    if decision.get("action") != "press_sequence":
        return "review"
    if expected and keys != expected:
        return "review"
    return "pass"


def markdown_report(report: dict[str, Any]) -> str:
    response = report.get("response") or {}
    decision = response.get("decision") or {}
    controller = response.get("controller") or {}
    prediction = response.get("prediction") or {}
    lines = [
        "# Agent Step Inline Smoke",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Server: `{report['server']}`",
        f"- Image: `{report['image']}`",
        f"- Status: `{report['status']}`",
        "- Scope: calls `/agent/step` with an inline image; no daemon capture, no key input, no live mode.",
        "",
        "## Result",
        "",
        f"- Controller: `{json.dumps(controller, ensure_ascii=False)}`",
        f"- Prediction sequence: `{prediction.get('sequence_text')}`",
        f"- Decision: `{json.dumps(decision, ensure_ascii=False)}`",
        f"- Expected sequence: `{report.get('expected_sequence')}`",
        f"- Latency: `{response.get('latency_ms')} ms`",
    ]
    if report.get("error"):
        lines.extend(["", "## Error", "", f"`{report['error']}`"])
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = args.image.resolve()
    expected = expected_sequence(args.expected_sequence)

    payload = {
        "image_b64": image_to_base64(image_path),
        "controller": "vision_rule",
        "mode": "observe",
        "sensors": ["template", "classifier"],
        "min_action_confidence": args.min_action_confidence,
    }

    started = time.perf_counter()
    response: dict[str, Any] | None = None
    error: str | None = None
    try:
        response = post_agent_step(args.server, payload, args.timeout_sec)
        status = classify_response(response, expected)
    except Exception as exc:
        status = "error"
        error = f"{type(exc).__name__}: {exc}"

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "server": args.server,
        "image": str(image_path),
        "expected_sequence": expected,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "status": status,
        "response": response,
        "error": error,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{status}: inline /agent/step vision_rule smoke")
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
