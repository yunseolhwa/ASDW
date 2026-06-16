from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


DEFAULT_OUTPUT_DIR = Path("artifacts/fusion-review-bundle/latest")


REPORTS = [
    {
        "id": "fusion_snapshot",
        "title": "Fusion Server Snapshot",
        "path": Path("artifacts/fusion-review/latest/report.json"),
        "md_path": Path("artifacts/fusion-review/latest/report.md"),
    },
    {
        "id": "contract",
        "title": "Contract And Safety Gates",
        "path": Path("artifacts/fusion-contract/latest/report.json"),
        "md_path": Path("artifacts/fusion-contract/latest/report.md"),
    },
    {
        "id": "agent_policy",
        "title": "Agent Observe/Rehearse Policy Smoke",
        "path": Path("artifacts/agent-policy-smoke/latest/report.json"),
        "md_path": Path("artifacts/agent-policy-smoke/latest/report.md"),
    },
    {
        "id": "gpu_server",
        "title": "WSL ROCm GPU Server Smoke",
        "path": Path("artifacts/gpu-server-smoke/latest/report.json"),
        "md_path": Path("artifacts/gpu-server-smoke/latest/report.md"),
    },
    {
        "id": "dataset_readiness",
        "title": "GUI Dataset Metadata Readiness",
        "path": Path("artifacts/gui-dataset-readiness/latest/report.json"),
        "md_path": Path("artifacts/gui-dataset-readiness/latest/report.md"),
    },
    {
        "id": "screenspot_pro",
        "title": "ScreenSpot-Pro Tiny External Boxes",
        "path": Path("artifacts/screenspot-pro-tiny/latest/report.json"),
        "md_path": Path("artifacts/screenspot-pro-tiny/latest/report.md"),
    },
    {
        "id": "ui_elements",
        "title": "UI-Elements Tiny Grounding",
        "path": Path("artifacts/ui-elements-tiny/latest/report.json"),
        "md_path": Path("artifacts/ui-elements-tiny/latest/report.md"),
    },
    {
        "id": "groundcua",
        "title": "GroundCUA Tiny Grounding",
        "path": Path("artifacts/groundcua-tiny/latest/report.json"),
        "md_path": Path("artifacts/groundcua-tiny/latest/report.md"),
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build one review index for the current fusion module artifacts.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--daemon", default="http://127.0.0.1:7870")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timeout-sec", type=float, default=3.0)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_info(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path)}
    stat = path.stat()
    return {
        "exists": True,
        "path": str(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
    }


def probe_get(url: str, timeout_sec: float) -> dict[str, Any]:
    try:
        response = requests.get(url, timeout=timeout_sec)
        payload = response.json()
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "payload": payload,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def probe_post(url: str, timeout_sec: float, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = requests.post(url, json=payload or {}, timeout=timeout_sec)
        data = response.json()
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "payload": data,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def summarize_report(report_id: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"summary": "unrecognized report schema"}
    if report_id == "fusion_snapshot":
        predictions = data.get("predictions") or []
        dataset = data.get("dataset_evaluation") or {}
        return {
            "server": data.get("server"),
            "expected_sequence": data.get("expected_sequence"),
            "prediction_rows": [
                {
                    "sensors": ",".join(row.get("sensors") or []),
                    "sequence_text": row.get("sequence_text"),
                    "matches_expected": row.get("matches_expected"),
                    "detections": row.get("detections"),
                    "latency_ms": row.get("latency_ms"),
                }
                for row in predictions
            ],
            "dataset": {
                "box_source": dataset.get("box_source"),
                "samples": dataset.get("samples"),
                "sequence_correct": dataset.get("sequence_correct"),
                "sequence_accuracy": dataset.get("sequence_accuracy"),
                "detection_count_matches": dataset.get("detection_count_matches"),
            }
            if dataset
            else None,
        }
    if report_id == "contract":
        return {
            "status": data.get("status"),
            "passed": data.get("passed"),
            "total": data.get("total"),
        }
    if report_id == "agent_policy":
        cases = data.get("cases") or []
        return {
            "status": data.get("status"),
            "passed": sum(1 for case in cases if case.get("status") == "pass"),
            "total": len(cases),
            "cases": {case.get("name"): case.get("status") for case in cases},
            "queue_after": data.get("queue_after"),
        }
    if report_id == "gpu_server":
        prediction = data.get("prediction_summary") or {}
        post_status = data.get("post_status") or {}
        checks = data.get("checks") or []
        return {
            "status": data.get("status"),
            "passed": sum(1 for check in checks if check.get("status") == "pass"),
            "total": len(checks),
            "prediction_device": prediction.get("device"),
            "post_status_device": post_status.get("device"),
            "sequence_text": prediction.get("sequence_text"),
            "latency_ms": prediction.get("latency_ms"),
        }
    if report_id == "dataset_readiness":
        datasets = data.get("datasets") or []
        return {
            "datasets": [
                {
                    "repo_id": item.get("repo_id"),
                    "readiness": item.get("readiness"),
                    "known_size_gb": item.get("total_known_size_gb"),
                }
                for item in datasets
            ]
        }
    if report_id == "screenspot_pro":
        samples = data.get("samples") or []
        accepted = sum_int((item.get("grounding_summary") or {}).get("accepted_count") for item in samples)
        rejected = sum_int((item.get("grounding_summary") or {}).get("rejected_count") for item in samples)
        return {
            "repo_id": data.get("repo_id"),
            "samples": len(samples),
            "elements": len(samples),
            "accepted": accepted,
            "rejected": rejected,
            "errors": [item.get("grounding_error") or item.get("error") for item in samples if item.get("grounding_error") or item.get("error")],
        }
    if report_id in {"ui_elements", "groundcua"}:
        samples = data.get("samples") or []
        accepted = sum_int(item.get("accepted_count") for item in samples)
        rejected = sum_int(item.get("rejected_count") for item in samples)
        elements = sum_int(item.get("element_count", 1) for item in samples)
        return {
            "repo_id": data.get("repo_id"),
            "samples": len(samples),
            "elements": elements,
            "accepted": accepted,
            "rejected": rejected,
            "errors": [item.get("grounding_error") or item.get("error") for item in samples if item.get("grounding_error") or item.get("error")],
        }
    return {"generated_at": data.get("generated_at") or data.get("generated_at_local")}


def sum_int(values: Any) -> int:
    total = 0
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += int(value)
    return total


def collect_reports() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in REPORTS:
        path = spec["path"]
        row = {
            "id": spec["id"],
            "title": spec["title"],
            "json": file_info(path),
            "markdown": file_info(spec["md_path"]),
        }
        if path.exists():
            try:
                data = read_json(path)
                row["summary"] = summarize_report(spec["id"], data)
            except Exception as exc:
                row["summary_error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
    return rows


def runtime_summary(server: str, daemon: str, timeout_sec: float) -> dict[str, Any]:
    fusion = probe_get(f"{server.rstrip('/')}/fusion/status", timeout_sec)
    agent = probe_get(f"{server.rstrip('/')}/agent/status", timeout_sec)
    llm = probe_post(f"{server.rstrip('/')}/llm/check", min(timeout_sec, 3.0), {})
    daemon_ping = probe_get(f"{daemon.rstrip('/')}/ping", timeout_sec)
    daemon_queue = probe_get(f"{daemon.rstrip('/')}/queue/status", timeout_sec)
    return {
        "server": server,
        "daemon": daemon,
        "fusion_status": compact_probe(fusion, ["ok", "device", "baseline_sensors", "candidate_sensors", "loaded_sensors", "evidence_endpoints"]),
        "agent_status": compact_agent_probe(agent),
        "llm_check": compact_probe(llm, ["ok", "base_url", "model", "rtt_ms", "error"]),
        "daemon_ping": compact_probe(daemon_ping, ["ok", "uptime_sec", "privilege"]),
        "daemon_queue": compact_probe(daemon_queue, ["active", "queued_count", "last_completed"]),
    }


def compact_probe(probe: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    if not probe.get("ok"):
        payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
        return {
            "ok": False,
            "status_code": probe.get("status_code"),
            "error": probe.get("error") or payload.get("error"),
            **{field: payload.get(field) for field in fields if field in payload},
        }
    payload = probe.get("payload") if isinstance(probe.get("payload"), dict) else {}
    return {
        "ok": True,
        **{field: payload.get(field) for field in fields if field in payload},
    }


def compact_agent_probe(probe: dict[str, Any]) -> dict[str, Any]:
    if not probe.get("ok"):
        return {"ok": False, "error": probe.get("error")}
    payload = probe.get("payload") or {}
    return {
        "ok": True,
        "vision": payload.get("vision"),
        "daemon_online": ((payload.get("daemon") or {}).get("online")),
        "llm_ok": ((payload.get("llm") or {}).get("ok")),
        "agent": payload.get("agent"),
    }


def review_gate(report: dict[str, Any]) -> dict[str, Any]:
    rows = {item["id"]: item for item in report["reports"]}
    contract = ((rows.get("contract") or {}).get("summary") or {})
    agent_policy = ((rows.get("agent_policy") or {}).get("summary") or {})
    ui = ((rows.get("ui_elements") or {}).get("summary") or {})
    groundcua = ((rows.get("groundcua") or {}).get("summary") or {})
    screenspot = ((rows.get("screenspot_pro") or {}).get("summary") or {})
    fusion = ((rows.get("fusion_snapshot") or {}).get("summary") or {})
    gpu = ((rows.get("gpu_server") or {}).get("summary") or {})

    checks = [
        {
            "name": "contract safety gates",
            "status": "pass" if contract.get("status") == "pass" and contract.get("passed") == contract.get("total") else "review",
            "evidence": f"{contract.get('passed')}/{contract.get('total')}",
        },
        {
            "name": "baseline ASDW fusion sample",
            "status": "pass" if any(row.get("sensors") == "template,classifier" and row.get("matches_expected") for row in fusion.get("prediction_rows") or []) else "review",
            "evidence": "template,classifier expected sequence match",
        },
        {
            "name": "external-box synthetic dataset",
            "status": "pass" if ((fusion.get("dataset") or {}).get("sequence_accuracy") or 0) >= 0.9 else "review",
            "evidence": json.dumps(fusion.get("dataset"), ensure_ascii=False),
        },
        {
            "name": "non-Minecraft GUI evidence plumbing",
            "status": "pass" if all((item.get("errors") == [] and item.get("accepted", 0) > 0) for item in [screenspot, ui, groundcua]) else "review",
            "evidence": f"ScreenSpot={screenspot.get('accepted')}, UI-Elements={ui.get('accepted')}, GroundCUA={groundcua.get('accepted')}",
        },
        {
            "name": "live input remains gated",
            "status": "pass" if agent_policy.get("status") == "pass" else "review",
            "evidence": json.dumps(agent_policy, ensure_ascii=False),
        },
        {
            "name": "WSL ROCm GPU server smoke",
            "status": "pass" if gpu.get("status") == "pass" and gpu.get("prediction_device") == "cuda" else "review",
            "evidence": json.dumps(gpu, ensure_ascii=False),
        },
        {
            "name": "SGLang runtime",
            "status": "offline" if not ((report.get("runtime") or {}).get("llm_check") or {}).get("ok") else "pass",
            "evidence": ((report.get("runtime") or {}).get("llm_check") or {}).get("error"),
        },
    ]
    return {
        "overall": "reviewable_with_known_gaps",
        "checks": checks,
    }


def markdown_report(report: dict[str, Any]) -> str:
    gate = report["review_gate"]
    lines = [
        "# Fusion Review Bundle",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Overall: `{gate['overall']}`",
        "- Scope: safe review bundle only; no input endpoint is called.",
        "",
        "## Review Gate",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in gate["checks"]:
        lines.append(
            f"| {escape_md(check['name'])} | `{check['status']}` | {escape_md(check.get('evidence'))} |"
        )

    lines.extend(
        [
            "",
            "## Runtime Snapshot",
            "",
            f"- Fusion server: `{json.dumps(report['runtime'].get('fusion_status'), ensure_ascii=False)}`",
            f"- Agent: `{json.dumps(report['runtime'].get('agent_status'), ensure_ascii=False)}`",
            f"- LLM: `{json.dumps(report['runtime'].get('llm_check'), ensure_ascii=False)}`",
            f"- Daemon queue: `{json.dumps(report['runtime'].get('daemon_queue'), ensure_ascii=False)}`",
            "",
            "## Artifact Index",
            "",
            "| Artifact | JSON | Markdown | Summary |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in report["reports"]:
        lines.append(
            "| {title} | {json_path} | {md_path} | {summary} |".format(
                title=escape_md(item["title"]),
                json_path=path_cell(item["json"]),
                md_path=path_cell(item["markdown"]),
                summary=escape_md(json.dumps(item.get("summary") or item.get("summary_error"), ensure_ascii=False)),
            )
        )

    lines.extend(
        [
            "",
            "## Known Gaps",
            "",
            "- SGLang/local LLM runtime is not online in the current snapshot unless the LLM row says `pass`.",
            "- `live + allow_live_input=true` was not executed.",
            "- Optional providers and real app/game task success remain separate validation work.",
            "- Current background WSL review server may report CPU device; GPU smoke is tracked separately in `artifacts/gpu-server-smoke/latest/report.md`.",
            "- Long-running GPU/daemon soak and target-specific task success remain separate validation work.",
        ]
    )
    return "\n".join(lines) + "\n"


def path_cell(info: dict[str, Any]) -> str:
    if not info.get("exists"):
        return "`missing`"
    return f"`{info['path']}`"


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "runtime": runtime_summary(args.server, args.daemon, args.timeout_sec),
        "reports": collect_reports(),
    }
    report["review_gate"] = review_gate(report)

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(report["review_gate"]["overall"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
