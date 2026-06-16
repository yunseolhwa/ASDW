from __future__ import annotations

import argparse
import base64
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw


REPO_ID = "ServiceNow/GroundCUA"
DEFAULT_OUTPUT_DIR = Path("artifacts/groundcua-tiny/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download tiny GroundCUA samples and test /grounding/review with annotated UI boxes.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-samples", type=int, default=2)
    parser.add_argument("--max-elements", type=int, default=20)
    parser.add_argument(
        "--min-json-size",
        type=int,
        default=1000,
        help="Skip tiny one-element annotations by default.",
    )
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("artifacts/hf-samples/groundcua"),
        help="Local artifact directory for the tiny downloaded subset.",
    )
    return parser.parse_args()


def load_hf_tools() -> tuple[Any, Any]:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "review_groundcua_tiny.py needs huggingface_hub. "
            "Run with `.venv-wsl/bin/python scripts/review_groundcua_tiny.py`."
        ) from exc
    return HfApi, hf_hub_download


def choose_pairs(api: Any, max_samples: int, min_json_size: int) -> list[dict[str, Any]]:
    if max_samples <= 0:
        return []
    info = api().dataset_info(REPO_ID, files_metadata=True)
    files = {str(item.rfilename): item for item in info.siblings or []}
    candidates: list[dict[str, Any]] = []
    for json_path, json_item in files.items():
        if not json_path.startswith("data/") or not json_path.endswith(".json"):
            continue
        platform, stem = platform_and_stem(json_path, "data")
        if not platform or not stem:
            continue
        image_path = f"images/{platform}/{stem}.png"
        if image_path not in files:
            continue
        image_item = files[image_path]
        json_size = int(getattr(json_item, "size", 0) or 0)
        if json_size < min_json_size:
            continue
        candidates.append(
            {
                "platform": platform,
                "stem": stem,
                "image_path": image_path,
                "json_path": json_path,
                "image_size_bytes": int(getattr(image_item, "size", 0) or 0),
                "json_size_bytes": json_size,
            }
        )
    candidates.sort(key=lambda item: (item["image_size_bytes"], item["json_path"]))

    pairs: list[dict[str, Any]] = []
    seen_platforms: set[str] = set()
    for candidate in candidates:
        if candidate["platform"] in seen_platforms:
            continue
        seen_platforms.add(candidate["platform"])
        pairs.append(candidate)
        if len(pairs) >= max_samples:
            break
    return pairs


def platform_and_stem(path: str, root: str) -> tuple[str | None, str | None]:
    prefix = f"{root}/"
    if not path.startswith(prefix):
        return None, None
    rest = path[len(prefix) :]
    if "/" not in rest:
        return None, None
    platform, filename = rest.rsplit("/", 1)
    return platform, Path(filename).stem


def download_file(hf_hub_download: Any, filename: str, download_dir: Path) -> Path:
    path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename=filename,
        local_dir=download_dir,
    )
    return Path(path)


def parse_groundcua_elements(json_path: Path, image_size: tuple[int, int], max_elements: int) -> list[dict[str, Any]]:
    width, height = image_size
    raw_rows = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw_rows, list):
        raise ValueError(f"Expected GroundCUA JSON list in {json_path}")

    elements: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            continue
        box = normalize_box(row.get("bbox"), width, height)
        if box is None:
            continue
        text = clean_text(row.get("text"))
        category = clean_text(row.get("category")) or "unknown"
        elements.append(
            {
                "id": str(row.get("id") or f"groundcua-{index}"),
                "label": text or category,
                "text": text,
                "category": category,
                "source": "groundcua-annotation",
                "box": box,
                "metadata": {
                    "row_index": index,
                    "image_path": row.get("image_path"),
                },
            }
        )
        if len(elements) >= max_elements:
            break
    return elements


def normalize_box(raw_box: Any, width: int, height: int) -> list[int] | None:
    if not isinstance(raw_box, list) or len(raw_box) != 4:
        return None
    try:
        x1, y1, x2, y2 = [float(value) for value in raw_box]
    except (TypeError, ValueError):
        return None
    x1, x2 = sorted((max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))))
    y1, y2 = sorted((max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))))
    if x2 <= x1 or y2 <= y1:
        return None
    int_box = [round(x1), round(y1), round(x2), round(y2)]
    if int_box[2] <= int_box[0] or int_box[3] <= int_box[1]:
        return None
    return int_box


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def post_grounding_review(
    server: str,
    image_path: Path,
    elements: list[dict[str, Any]],
    timeout_sec: float,
) -> dict[str, Any]:
    instruction_terms = sorted(
        {
            token
            for element in elements[:8]
            for token in (element.get("text") or element.get("category") or "").lower().split()
            if token
        }
    )
    instruction = "review desktop UI elements " + " ".join(instruction_terms[:12])
    payload = {
        "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        "instruction": instruction,
        "source": REPO_ID,
        "elements": elements,
    }
    response = requests.post(
        f"{server.rstrip('/')}/grounding/review",
        json=payload,
        timeout=timeout_sec,
    )
    response.raise_for_status()
    return response.json()


def draw_overlay(image_path: Path, elements: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    colors = [
        (255, 80, 80),
        (80, 160, 255),
        (80, 210, 120),
        (230, 180, 70),
        (210, 120, 255),
    ]
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        for index, element in enumerate(elements):
            box = element["box"]
            color = colors[index % len(colors)]
            label = str(element.get("label") or element.get("category") or "")[:32]
            draw.rectangle(box, outline=color, width=3)
            draw.text((box[0] + 2, max(0, box[1] - 12)), label, fill=color)
        image.save(output_path)


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def clear_previous_overlays(output_dir: Path) -> None:
    overlay_dir = output_dir / "overlays"
    if not overlay_dir.exists():
        return
    for path in overlay_dir.glob("*.png"):
        path.unlink()


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# GroundCUA Tiny Grounding Review",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Dataset: [`{REPO_ID}`](https://huggingface.co/datasets/{REPO_ID})",
        f"- Server: `{report['server']}`",
        "- Scope: tiny annotated sample only; verifies `/grounding/review` on desktop UI boxes.",
        "- It does not call `/predict` or any input endpoint.",
        "",
        "| Platform | Stem | Elements | Accepted | Categories | Overlay |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for sample in report["samples"]:
        lines.append(
            "| {platform} | {stem} | {elements} | {accepted} | {categories} | {overlay} |".format(
                platform=escape_md(sample["platform"]),
                stem=escape_md(sample["stem"][:16]),
                elements=sample["element_count"],
                accepted=sample.get("accepted_count"),
                categories=escape_md(", ".join(f"{key}:{value}" for key, value in sample["category_counts"].items())),
                overlay=escape_md(sample["overlay_path"]),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- This validates the generic GUI evidence boundary on GroundCUA desktop annotations.",
            "- GroundCUA boxes are treated as external provider output and mapped into `/grounding/review` without adding a runtime dependency.",
            "- This is not a live automation test and does not prove provider accuracy on unseen applications.",
        ]
    )
    return "\n".join(lines) + "\n"


def escape_md(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def main() -> int:
    args = parse_args()
    HfApi, hf_hub_download = load_hf_tools()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    clear_previous_overlays(output_dir)
    download_dir = args.download_dir.resolve()

    pairs = choose_pairs(HfApi, args.max_samples, args.min_json_size)
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        image_path = download_file(hf_hub_download, pair["image_path"], download_dir)
        json_path = download_file(hf_hub_download, pair["json_path"], download_dir)
        with Image.open(image_path) as image:
            image_size = image.size
        elements = parse_groundcua_elements(json_path, image_size, args.max_elements)
        overlay_name = safe_filename(f"{pair['platform']}-{pair['stem']}.png")
        overlay_path = output_dir / "overlays" / overlay_name
        draw_overlay(image_path, elements, overlay_path)
        try:
            grounding = post_grounding_review(args.server, image_path, elements, args.timeout_sec)
            grounding_error = None
        except Exception as exc:
            grounding = None
            grounding_error = f"{type(exc).__name__}: {exc}"
        category_counts = dict(Counter(str(element["category"]) for element in elements))
        rows.append(
            {
                **pair,
                "downloaded_image": str(image_path),
                "downloaded_json": str(json_path),
                "image_size": list(image_size),
                "element_count": len(elements),
                "category_counts": category_counts,
                "overlay_path": str(overlay_path),
                "accepted_count": grounding.get("accepted_count") if grounding else None,
                "rejected_count": grounding.get("rejected_count") if grounding else None,
                "latency_ms": grounding.get("latency_ms") if grounding else None,
                "first_elements": (grounding.get("elements") or [])[:5] if grounding else [],
                "grounding_error": grounding_error,
            }
        )

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "server": args.server,
        "repo_id": REPO_ID,
        "download_dir": str(download_dir),
        "max_samples": args.max_samples,
        "max_elements": args.max_elements,
        "min_json_size": args.min_json_size,
        "samples": rows,
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
