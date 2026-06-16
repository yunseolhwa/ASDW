from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BUNDLE = Path("artifacts/fusion-review-bundle/latest/report.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/fusion-readiness-audit/latest")

REQUIRED_DOCS = [
    Path("README.md"),
    Path("ENVIRONMENT_LOCK.md"),
    Path("TODO-local-daemon-and-llm.md"),
    Path("docs/README.md"),
    Path("docs/fusion-module-knowledge.md"),
    Path("docs/fusion-review-state.md"),
]

REQUIRED_SCRIPTS = [
    Path("scripts/build_fusion_review_bundle.py"),
    Path("scripts/verify_fusion_contracts.py"),
    Path("scripts/smoke_agent_policy.py"),
    Path("scripts/smoke_server_wsl_gpu.py"),
    Path("scripts/gui_dataset_readiness.py"),
    Path("scripts/review_screenspot_pro_tiny.py"),
    Path("scripts/review_ui_elements_tiny.py"),
    Path("scripts/review_groundcua_tiny.py"),
]

PINNED_REQUIREMENTS = [
    Path("requirements-windows.txt"),
    Path("requirements-wsl-rocm.txt"),
    Path("requirements-windows-strong.txt"),
]

EXPECTED_ALLOWED_GAPS = [
    "SGLang/local LLM runtime is not online",
    "live + allow_live_input=true",
    "Optional providers and real app/game task success",
    "Long-running GPU/daemon soak",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit whether the fusion module is reviewable from generated reports.",
    )
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def find_report(reports: list[dict[str, Any]], report_id: str) -> dict[str, Any]:
    for item in reports:
        if item.get("id") == report_id:
            return item
    return {}


def find_gate(gates: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for item in gates:
        if item.get("name") == name:
            return item
    return {}


def check_file_exists(path: Path) -> dict[str, Any]:
    return {
        "name": f"file exists: {path.as_posix()}",
        "status": "pass" if path.exists() else "fail",
        "evidence": str(path),
    }


def check_requirements_pinned(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"name": f"requirements pinned: {path}", "status": "fail", "evidence": "missing"}
    unpinned: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            unpinned.append(line)
    return {
        "name": f"requirements pinned: {path.as_posix()}",
        "status": "pass" if not unpinned else "review",
        "evidence": "all direct entries pinned" if not unpinned else f"unpinned entries: {unpinned}",
    }


def check_gate(gates: list[dict[str, Any]], name: str, expected_status: str = "pass") -> dict[str, Any]:
    gate = find_gate(gates, name)
    status = gate.get("status")
    return {
        "name": f"review gate: {name}",
        "status": "pass" if status == expected_status else "fail",
        "evidence": gate.get("evidence") or f"status={status}",
    }


def check_report_status(reports: list[dict[str, Any]], report_id: str, name: str) -> dict[str, Any]:
    report = find_report(reports, report_id)
    summary = report.get("summary") or {}
    status = summary.get("status")
    return {
        "name": f"artifact report: {name}",
        "status": "pass" if status == "pass" else "fail",
        "evidence": json.dumps(summary, ensure_ascii=False),
    }


def collect_checks(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    reports = bundle.get("reports") or []
    gates = ((bundle.get("review_gate") or {}).get("checks") or [])
    checks: list[dict[str, Any]] = []

    for path in REQUIRED_DOCS:
        checks.append(check_file_exists(path))
    for path in REQUIRED_SCRIPTS:
        checks.append(check_file_exists(path))
    for path in PINNED_REQUIREMENTS:
        checks.append(check_requirements_pinned(path))

    checks.extend(
        [
            check_gate(gates, "contract safety gates"),
            check_gate(gates, "baseline ASDW fusion sample"),
            check_gate(gates, "external-box synthetic dataset"),
            check_gate(gates, "non-Minecraft GUI evidence plumbing"),
            check_gate(gates, "live input remains gated"),
            check_gate(gates, "WSL ROCm GPU server smoke"),
            check_report_status(reports, "contract", "contract verifier"),
            check_report_status(reports, "agent_policy", "agent policy smoke"),
            check_report_status(reports, "gpu_server", "GPU server smoke"),
        ]
    )

    dataset = ((find_report(reports, "dataset_readiness").get("summary") or {}).get("datasets") or [])
    checks.append(
        {
            "name": "GUI dataset candidates are documented",
            "status": "pass" if len(dataset) >= 3 else "review",
            "evidence": json.dumps(dataset, ensure_ascii=False),
        }
    )

    llm_gate = find_gate(gates, "SGLang runtime")
    checks.append(
        {
            "name": "SGLang offline is explicit, not hidden",
            "status": "pass" if llm_gate.get("status") in {"offline", "pass"} else "review",
            "evidence": llm_gate.get("evidence"),
        }
    )

    known_gaps = bundle_known_gaps_text()
    checks.append(
        {
            "name": "known gaps are explicitly recorded",
            "status": "pass" if all(fragment in known_gaps for fragment in EXPECTED_ALLOWED_GAPS) else "review",
            "evidence": "expected allowed gaps present" if known_gaps else "bundle markdown missing",
        }
    )

    return checks


def bundle_known_gaps_text() -> str:
    path = Path("artifacts/fusion-review-bundle/latest/report.md")
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    marker = "## Known Gaps"
    if marker not in text:
        return ""
    return text.split(marker, 1)[1]


def summarize_status(checks: list[dict[str, Any]]) -> str:
    if any(item["status"] == "fail" for item in checks):
        return "not_reviewable"
    if any(item["status"] == "review" for item in checks):
        return "reviewable_with_manual_notes"
    return "reviewable"


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# Fusion Readiness Audit",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Status: `{report['status']}`",
        "- Scope: validates generated review evidence; does not call capture or input endpoints.",
        "",
        "## Checks",
        "",
        "| Check | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    for check in report["checks"]:
        lines.append(
            f"| {escape_md(check['name'])} | `{check['status']}` | {escape_md(check.get('evidence'))} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `reviewable` means the fusion module has enough current evidence for a human code/runtime review.",
            "- It does not mean live input, optional providers, SGLang runtime, or long-running soak are complete.",
            "- Those items remain explicit follow-up validation work, not hidden pass conditions.",
        ]
    )
    return "\n".join(lines) + "\n"


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_at_utc = datetime.now(timezone.utc)
    bundle_path = args.bundle.resolve()
    bundle = read_json(bundle_path)
    checks = collect_checks(bundle)
    status = summarize_status(checks)
    report = {
        "generated_at_local": generated_at_utc.astimezone().isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "status": status,
        "bundle": str(bundle_path),
        "checks": checks,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"{status}: {sum(1 for item in checks if item['status'] == 'pass')}/{len(checks)} checks passed")
    return 0 if status in {"reviewable", "reviewable_with_manual_notes"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
