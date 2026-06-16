from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_OUTPUT_DIR = Path("artifacts/agent-policy-smoke/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test /agent/act safety modes with direct decisions and no live input.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--daemon", default="http://127.0.0.1:7870")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    return parser.parse_args()


def post_json(url: str, payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    response = requests.post(url, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def get_json(url: str, timeout_sec: float) -> dict[str, Any]:
    response = requests.get(url, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def press_decision(confidence: float = 0.95) -> dict[str, Any]:
    return {
        "state": "captcha_prompt",
        "action": "press_sequence",
        "keys": ["A", "S", "D", "W"],
        "confidence": confidence,
        "reason": "smoke-test direct decision",
    }


def run_case(
    name: str,
    server: str,
    daemon: str,
    mode: str,
    timeout_sec: float,
    decision: dict[str, Any],
    allow_live_input: bool = False,
) -> dict[str, Any]:
    payload = {
        "daemon_url": daemon,
        "mode": mode,
        "allow_live_input": allow_live_input,
        "decision": decision,
        "input_provider": "builtin",
        "daemon_wait": True,
        "daemon_timeout_sec": min(timeout_sec, 30.0),
    }
    started = time.perf_counter()
    try:
        response = post_json(f"{server.rstrip('/')}/agent/act", payload, timeout_sec + 5.0)
        return {
            "name": name,
            "status": classify_case_result(name, response),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "response": response,
        }
    except Exception as exc:
        return {
            "name": name,
            "status": "error",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def classify_case_result(name: str, response: dict[str, Any]) -> str:
    action_result = response.get("action_result") or {}
    if name == "observe_skips_input":
        if response.get("ok") is True and action_result.get("status") == "skipped":
            return "pass"
    if name == "rehearse_uses_daemon_dry_run":
        daemon = action_result.get("daemon") or {}
        if response.get("ok") is True and action_result.get("dry_run") is True and daemon.get("dry_run") is True:
            return "pass"
    if name == "live_requires_explicit_allow":
        if response.get("ok") is False and action_result.get("status") == "blocked" and "allow_live_input" in str(action_result.get("reason")):
            return "pass"
    if name == "low_confidence_blocks":
        if response.get("ok") is False and action_result.get("status") == "blocked" and "below required" in str(action_result.get("reason")):
            return "pass"
    return "review"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Agent Policy Smoke",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Server: `{report['server']}`",
        f"- Daemon: `{report['daemon']}`",
        "- Scope: direct `/agent/act` decisions only; no capture, no LLM call, no live input.",
        "",
        "| Case | Status | Action Result |",
        "| --- | --- | --- |",
    ]
    for case in report["cases"]:
        action_result = (case.get("response") or {}).get("action_result") or {}
        lines.append(
            "| {name} | `{status}` | {summary} |".format(
                name=escape_md(case["name"]),
                status=case["status"],
                summary=escape_md(summarize_action_result(action_result) or case.get("error", "")),
            )
        )
    lines.extend(
        [
            "",
            "Queue:",
            "",
            f"- Before: `{json.dumps(report.get('queue_before'), ensure_ascii=False)}`",
            f"- After: `{json.dumps(report.get('queue_after'), ensure_ascii=False)}`",
            "",
            "Interpretation:",
            "",
            "- `observe` skips input even with an executable decision.",
            "- `rehearse` sends daemon `dry_run=true` and validates queue/timing without real key input.",
            "- `live` remains blocked unless `allow_live_input=true` is explicitly supplied.",
            "- Low-confidence executable decisions are blocked before daemon execution.",
        ]
    )
    return "\n".join(lines) + "\n"


def summarize_action_result(action_result: dict[str, Any]) -> str:
    if not action_result:
        return ""
    fields = {
        "ok": action_result.get("ok"),
        "status": action_result.get("status"),
        "dry_run": action_result.get("dry_run"),
        "reason": action_result.get("reason"),
    }
    daemon = action_result.get("daemon")
    if isinstance(daemon, dict):
        fields["daemon_status"] = daemon.get("status")
        fields["daemon_dry_run"] = daemon.get("dry_run")
        fields["daemon_provider"] = daemon.get("provider")
    return json.dumps(fields, ensure_ascii=False)


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    queue_before = safe_get_queue(args.daemon, args.timeout_sec)
    cases = [
        run_case("observe_skips_input", args.server, args.daemon, "observe", args.timeout_sec, press_decision()),
        run_case("rehearse_uses_daemon_dry_run", args.server, args.daemon, "rehearse", args.timeout_sec, press_decision()),
        run_case("live_requires_explicit_allow", args.server, args.daemon, "live", args.timeout_sec, press_decision()),
        run_case("low_confidence_blocks", args.server, args.daemon, "rehearse", args.timeout_sec, press_decision(0.20)),
    ]
    queue_after = safe_get_queue(args.daemon, args.timeout_sec)

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "server": args.server,
        "daemon": args.daemon,
        "scope": "direct /agent/act decisions only; no live input",
        "queue_before": compact_queue(queue_before),
        "queue_after": compact_queue(queue_after),
        "cases": cases,
        "status": "pass" if all(case["status"] == "pass" for case in cases) else "review",
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{report['status']}: {sum(1 for case in cases if case['status'] == 'pass')}/{len(cases)} cases passed")
    return 0 if report["status"] == "pass" else 1


def safe_get_queue(daemon: str, timeout_sec: float) -> dict[str, Any]:
    try:
        return get_json(f"{daemon.rstrip('/')}/queue/status", timeout_sec)
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def compact_queue(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": payload.get("ok", True) if "ok" in payload else True,
        "active": payload.get("active"),
        "queued_count": payload.get("queued_count"),
        "last_completed": payload.get("last_completed"),
        "error": payload.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
