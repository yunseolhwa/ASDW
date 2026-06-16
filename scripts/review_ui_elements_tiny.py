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


REPO_ID = "YashJain/UI-Elements-Detection-Dataset"
DEFAULT_OUTPUT_DIR = Path("artifacts/ui-elements-tiny/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download tiny UI-Elements samples and test /grounding/review with YOLO boxes.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-samples", type=int, default=2)
    parser.add_argument("--max-elements", type=int, default=12)
    parser.add_argument("--timeout-sec", type=float, default=60.0)
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("artifacts/hf-samples/ui-elements"),
        help="Local artifact directory for the tiny downloaded subset.",
    )
    return parser.parse_args()


def load_hf_tools() -> tuple[Any, Any]:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "review_ui_elements_tiny.py needs huggingface_hub. "
            "Run with `.venv-wsl/bin/python scripts/review_ui_elements_tiny.py`."
        ) from exc
    return HfApi, hf_hub_download


def parse_class_names(text: str) -> dict[int, str]:
    names: dict[int, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not key.isdigit():
            continue
        names[int(key)] = value.strip().strip("'\"")
    return names


def choose_pairs(api: Any, max_samples: int) -> list[dict[str, Any]]:
    if max_samples <= 0:
        return []
    info = api().dataset_info(REPO_ID, files_metadata=True)
    files = {str(item.rfilename): item for item in info.siblings or []}
    candidates: list[dict[str, Any]] = []
    for label_path, label_item in files.items():
        if not label_path.endswith(".txt") or "/labels/" not in label_path:
            continue
        stem = Path(label_path).stem
        split_prefix = label_path.split("/labels/", 1)[0]
        image_path = first_existing_image(files, split_prefix, stem)
        if image_path is None:
            continue
        image_item = files[image_path]
        candidates.append(
            {
                "stem": stem,
                "split": split_prefix.replace("/", ":"),
                "image_path": image_path,
                "label_path": label_path,
                "image_size_bytes": int(getattr(image_item, "size", 0) or 0),
                "label_size_bytes": int(getattr(label_item, "size", 0) or 0),
            }
        )
    candidates.sort(key=lambda item: (item["image_size_bytes"], item["image_path"]))

    pairs: list[dict[str, Any]] = []
    seen_stems: set[str] = set()
    for candidate in candidates:
        if candidate["stem"] in seen_stems:
            continue
        seen_stems.add(candidate["stem"])
        pairs.append(candidate)
        if len(pairs) >= max_samples:
            break
    return pairs


def first_existing_image(files: dict[str, Any], split_prefix: str, stem: str) -> str | None:
    for extension in [".png", ".jpg", ".jpeg", ".webp"]:
        path = f"{split_prefix}/images/{stem}{extension}"
        if path in files:
            return path
    return None


def download_file(hf_hub_download: Any, filename: str, download_dir: Path) -> Path:
    path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename=filename,
        local_dir=download_dir,
    )
    return Path(path)


def parse_yolo_labels(label_path: Path, image_size: tuple[int, int], class_names: dict[int, str], max_elements: int) -> list[dict[str, Any]]:
    width, height = image_size
    elements: list[dict[str, Any]] = []
    for index, line in enumerate(label_path.read_text(encoding="utf-8").splitlines()):
        parts = line.split()
        if len(parts) < 5:
            continue
        class_id = int(float(parts[0]))
        cx, cy, box_w, box_h = [float(value) for value in parts[1:5]]
        x1 = round((cx - box_w / 2) * width)
        y1 = round((cy - box_h / 2) * height)
        x2 = round((cx + box_w / 2) * width)
        y2 = round((cy + box_h / 2) * height)
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        class_name = class_names.get(class_id, f"class_{class_id}")
        elements.append(
            {
                "id": f"yolo-{index}",
                "label": class_name,
                "text": class_name,
                "category": "ui-element",
                "source": "ui-elements-yolo",
                "box": [x1, y1, x2, y2],
                "metadata": {
                    "class_id": class_id,
                    "yolo": [cx, cy, box_w, box_h],
                    "row_index": index,
                },
            }
        )
        if len(elements) >= max_elements:
            break
    return elements


def post_grounding_review(
    server: str,
    image_path: Path,
    elements: list[dict[str, Any]],
    timeout_sec: float,
) -> dict[str, Any]:
    payload = {
        "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        "instruction": "review link button input checkbox menu icon UI elements",
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
    colors = {
        "link": (255, 80, 80),
        "button": (80, 160, 255),
        "input": (80, 210, 120),
        "checkbox": (230, 180, 70),
        "icon": (210, 120, 255),
    }
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        for element in elements:
            box = element["box"]
            color = colors.get(str(element.get("label")), (255, 40, 40))
            draw.rectangle(box, outline=color, width=3)
            draw.text((box[0] + 2, max(0, box[1] - 12)), str(element.get("label", "")), fill=color)
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
        "# UI-Elements Tiny Grounding Review",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Dataset: [`{REPO_ID}`](https://huggingface.co/datasets/{REPO_ID})",
        f"- Server: `{report['server']}`",
        "- Scope: tiny YOLO sample only; verifies `/grounding/review` on general web/UI element boxes.",
        "- It does not call `/predict` or any input endpoint.",
        "",
        "| Sample | Split | Elements | Accepted | Classes | Overlay |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for sample in report["samples"]:
        lines.append(
            "| {stem} | {split} | {elements} | {accepted} | {classes} | {overlay} |".format(
                stem=escape_md(sample["stem"]),
                split=escape_md(sample["split"]),
                elements=sample["element_count"],
                accepted=sample.get("accepted_count"),
                classes=escape_md(", ".join(f"{key}:{value}" for key, value in sample["class_counts"].items())),
                overlay=escape_md(sample["overlay_path"]),
            )
        )
    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- This validates the generic GUI evidence boundary with multiple web/UI boxes, not ASDW key classification.",
            "- The YOLO labels are treated as an external provider output and mapped into `/grounding/review` without adding a runtime dependency.",
            "- Provider accuracy is still a separate question; this report only proves the review pipeline and artifact shape.",
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

    dataset_yaml = download_file(hf_hub_download, "dataset.yaml", download_dir)
    class_names = parse_class_names(dataset_yaml.read_text(encoding="utf-8"))
    pairs = choose_pairs(HfApi, args.max_samples)

    rows: list[dict[str, Any]] = []
    for pair in pairs:
        image_path = download_file(hf_hub_download, pair["image_path"], download_dir)
        label_path = download_file(hf_hub_download, pair["label_path"], download_dir)
        with Image.open(image_path) as image:
            image_size = image.size
        elements = parse_yolo_labels(label_path, image_size, class_names, args.max_elements)
        overlay_name = safe_filename(f"{pair['split']}-{pair['stem']}.png")
        overlay_path = output_dir / "overlays" / overlay_name
        draw_overlay(image_path, elements, overlay_path)
        try:
            grounding = post_grounding_review(args.server, image_path, elements, args.timeout_sec)
            grounding_error = None
        except Exception as exc:
            grounding = None
            grounding_error = f"{type(exc).__name__}: {exc}"
        class_counts = dict(Counter(str(element["label"]) for element in elements))
        rows.append(
            {
                **pair,
                "downloaded_image": str(image_path),
                "downloaded_label": str(label_path),
                "image_size": list(image_size),
                "element_count": len(elements),
                "class_counts": class_counts,
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
        "class_names": class_names,
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
