from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("artifacts/gui-dataset-readiness/latest")
DEFAULT_DATASETS = [
    {
        "repo_id": "rootsautomation/ScreenSpot",
        "purpose": "general GUI grounding benchmark",
        "source_url": "https://huggingface.co/datasets/rootsautomation/ScreenSpot",
    },
    {
        "repo_id": "Voxel51/ScreenSpot-Pro",
        "purpose": "professional high-resolution GUI grounding benchmark",
        "source_url": "https://huggingface.co/datasets/Voxel51/ScreenSpot-Pro",
    },
    {
        "repo_id": "ServiceNow/GroundCUA",
        "purpose": "dense desktop UI element grounding and computer-use perception",
        "source_url": "https://huggingface.co/datasets/ServiceNow/GroundCUA",
    },
    {
        "repo_id": "rootsautomation/RICO-ScreenQA",
        "purpose": "mobile UI screen/question grounding and UI understanding",
        "source_url": "https://huggingface.co/datasets/rootsautomation/RICO-ScreenQA",
    },
    {
        "repo_id": "YashJain/UI-Elements-Detection-Dataset",
        "purpose": "UI element detection candidate",
        "source_url": "https://huggingface.co/datasets/YashJain/UI-Elements-Detection-Dataset",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Hugging Face GUI dataset candidates without downloading large data files.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--repo",
        action="append",
        default=[],
        help="Additional Hugging Face dataset repo id. Can be passed multiple times.",
    )
    parser.add_argument("--max-sample-files", type=int, default=12)
    return parser.parse_args()


def load_hf_api() -> Any:
    try:
        from huggingface_hub import HfApi
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "gui_dataset_readiness.py needs huggingface_hub. "
            "Run it with `.venv-wsl/bin/python scripts/gui_dataset_readiness.py`."
        ) from exc
    return HfApi()


def inspect_dataset(api: Any, dataset: dict[str, str], max_sample_files: int) -> dict[str, Any]:
    repo_id = dataset["repo_id"]
    result: dict[str, Any] = {
        "repo_id": repo_id,
        "purpose": dataset.get("purpose"),
        "source_url": dataset.get("source_url"),
    }
    try:
        info = api.dataset_info(repo_id, files_metadata=True)
    except Exception as exc:
        result.update(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "readiness": "unavailable",
                "recommended_next_step": "Check repo id, network, or authentication before using this candidate.",
            }
        )
        return result

    siblings = list(info.siblings or [])
    file_rows = [file_summary(item) for item in siblings]
    ext_counts = Counter(row["extension"] for row in file_rows)
    top_dirs = Counter(row["top_dir"] for row in file_rows)
    total_known_size = sum(row["size"] or 0 for row in file_rows)
    result.update(
        {
            "ok": True,
            "private": bool(getattr(info, "private", False)),
            "gated": bool(getattr(info, "gated", False)),
            "downloads": getattr(info, "downloads", None),
            "likes": getattr(info, "likes", None),
            "last_modified": stringify_time(getattr(info, "last_modified", None)),
            "sha": getattr(info, "sha", None),
            "file_count": len(file_rows),
            "total_known_size_bytes": total_known_size,
            "total_known_size_gb": round(total_known_size / 1_000_000_000, 3),
            "extension_counts": dict(sorted(ext_counts.items())),
            "top_dirs": dict(top_dirs.most_common(10)),
            "sample_files": file_rows[:max_sample_files],
        }
    )
    result.update(classify_readiness(result))
    return result


def file_summary(item: Any) -> dict[str, Any]:
    filename = str(getattr(item, "rfilename", ""))
    path = Path(filename)
    suffix = path.suffix.lower() or "[none]"
    top_dir = filename.split("/", 1)[0] if "/" in filename else "[root]"
    return {
        "path": filename,
        "extension": suffix,
        "top_dir": top_dir,
        "size": getattr(item, "size", None),
    }


def classify_readiness(item: dict[str, Any]) -> dict[str, str]:
    if not item.get("ok"):
        return {"readiness": "unavailable", "recommended_next_step": "Fix metadata access first."}
    if item.get("private") or item.get("gated"):
        return {
            "readiness": "requires_auth_or_approval",
            "recommended_next_step": "Do not add to automation path until access and license are explicit.",
        }

    extensions = set(item.get("extension_counts", {}))
    has_direct_images = bool(extensions & {".png", ".jpg", ".jpeg", ".webp"})
    has_json = ".json" in extensions
    has_parquet = ".parquet" in extensions

    repo_id = str(item.get("repo_id", ""))
    if repo_id == "ServiceNow/GroundCUA":
        return {
            "readiness": "metadata_ready_large_direct_files",
            "recommended_next_step": "Use a platform subset and adapt JSON bbox entries into /predict boxes; avoid full download until subset criteria are fixed.",
        }
    if repo_id == "Voxel51/ScreenSpot-Pro":
        return {
            "readiness": "metadata_ready_large_benchmark",
            "recommended_next_step": "Use as high-resolution external-box benchmark; download a tiny reviewed sample first because screenshots are large.",
        }
    if has_parquet and not has_direct_images:
        return {
            "readiness": "metadata_ready_requires_parquet_reader",
            "recommended_next_step": "Keep out of baseline; evaluate only if parquet tooling is approved for an experiment.",
        }
    if has_direct_images and has_json:
        return {
            "readiness": "metadata_ready_direct_image_json",
            "recommended_next_step": "Build a tiny sample adapter that maps JSON boxes into /predict boxes.",
        }
    if has_direct_images:
        return {
            "readiness": "metadata_ready_images_only_or_custom_schema",
            "recommended_next_step": "Inspect README/schema before adapter work.",
        }
    return {
        "readiness": "metadata_ready_schema_unknown",
        "recommended_next_step": "Inspect README and file schema before any download.",
    }


def stringify_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# GUI Dataset Readiness",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        "- Scope: Hugging Face metadata inspection only; no large dataset files are downloaded.",
        "",
        "| Dataset | Readiness | Files | Known Size GB | Shape | Next Step |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for item in report["datasets"]:
        if not item.get("ok"):
            lines.append(
                f"| [{item['repo_id']}]({item.get('source_url', '')}) | `{item.get('readiness')}` |  |  | error | {escape_md(item.get('error', ''))} |"
            )
            continue
        shape = summarize_shape(item.get("extension_counts", {}))
        lines.append(
            "| [{repo}]({url}) | `{readiness}` | {files} | {size} | {shape} | {next_step} |".format(
                repo=item["repo_id"],
                url=item.get("source_url", ""),
                readiness=item.get("readiness", "unknown"),
                files=item.get("file_count", ""),
                size=item.get("total_known_size_gb", ""),
                shape=escape_md(shape),
                next_step=escape_md(item.get("recommended_next_step", "")),
            )
        )

    lines.extend(
        [
            "",
            "PM Interpretation:",
            "",
            "- ScreenSpot-Pro and GroundCUA are the strongest external GUI grounding candidates.",
            "- RICO/ScreenSpot parquet-packaged candidates stay outside the baseline until a parquet reader is intentionally approved.",
            "- This does not promote any dataset or parser to runtime baseline; it only creates a review queue for generalization evidence.",
            "",
            "Source Notes:",
            "",
            "- ScreenSpot-Pro is documented as a professional high-resolution GUI grounding benchmark with instructions and target boxes.",
            "- GroundCUA is documented as real UI screenshots with structured annotations and bounding boxes for computer-use agents.",
            "- OmniParser remains a parser/provider candidate, not a baseline dependency.",
        ]
    )
    return "\n".join(lines) + "\n"


def summarize_shape(extension_counts: dict[str, int]) -> str:
    important = []
    for extension in [".png", ".jpg", ".jpeg", ".json", ".parquet", ".md"]:
        if extension in extension_counts:
            important.append(f"{extension}:{extension_counts[extension]}")
    return ", ".join(important) if important else json.dumps(extension_counts, ensure_ascii=False)


def escape_md(value: str) -> str:
    return str(value).replace("|", "\\|")


def main() -> int:
    args = parse_args()
    api = load_hf_api()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    datasets = list(DEFAULT_DATASETS)
    for repo_id in args.repo:
        datasets.append(
            {
                "repo_id": repo_id,
                "purpose": "user-supplied GUI dataset candidate",
                "source_url": f"https://huggingface.co/datasets/{repo_id}",
            }
        )

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "tool": "huggingface_hub.dataset_info(files_metadata=True)",
        "download_policy": "metadata only; no large dataset files downloaded",
        "datasets": [inspect_dataset(api, item, args.max_sample_files) for item in datasets],
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
