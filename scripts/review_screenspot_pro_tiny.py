from __future__ import annotations

import argparse
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw


REPO_ID = "Voxel51/ScreenSpot-Pro"
DEFAULT_OUTPUT_DIR = Path("artifacts/screenspot-pro-tiny/latest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a tiny ScreenSpot-Pro sample and test /grounding/review plus /predict external boxes.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--max-samples", type=int, default=2)
    parser.add_argument("--sensors", default="template,classifier")
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=Path("artifacts/hf-samples/screenspot-pro"),
        help="Local artifact directory for the tiny downloaded subset.",
    )
    return parser.parse_args()


def load_hf_tools() -> tuple[Any, Any]:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "review_screenspot_pro_tiny.py needs huggingface_hub. "
            "Run with `.venv-wsl/bin/python scripts/review_screenspot_pro_tiny.py`."
        ) from exc
    return HfApi, hf_hub_download


def download_metadata(hf_hub_download: Any, download_dir: Path) -> list[dict[str, Any]]:
    path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename="samples.json",
        local_dir=download_dir,
    )
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(payload.get("samples") or [])


def choose_samples(api: Any, samples: list[dict[str, Any]], max_samples: int) -> list[dict[str, Any]]:
    sample_by_path = {
        str(sample.get("filepath")): sample
        for sample in samples
        if sample.get("filepath") and sample.get("action_detection")
    }
    info = api().dataset_info(REPO_ID, files_metadata=True)
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for item in info.siblings or []:
        filename = str(getattr(item, "rfilename", ""))
        if filename in sample_by_path and filename.lower().endswith(".png"):
            candidates.append((int(getattr(item, "size", 0) or 0), filename, sample_by_path[filename]))
    candidates.sort(key=lambda row: (row[0], row[1]))
    selected = []
    for size, filename, sample in candidates[: max(0, max_samples)]:
        selected.append({**sample, "_hf_size_bytes": size, "_hf_path": filename})
    return selected


def download_image(hf_hub_download: Any, filename: str, download_dir: Path) -> Path:
    path = hf_hub_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        filename=filename,
        local_dir=download_dir,
    )
    return Path(path)


def detection_box_xyxy(sample: dict[str, Any], image_size: tuple[int, int]) -> list[int]:
    detection = sample.get("action_detection") or {}
    box = detection.get("bounding_box")
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("sample action_detection.bounding_box must be [x, y, w, h]")
    width, height = image_size
    x, y, w, h = [float(value) for value in box]
    x1 = max(0, min(width, round(x * width)))
    y1 = max(0, min(height, round(y * height)))
    x2 = max(0, min(width, round((x + w) * width)))
    y2 = max(0, min(height, round((y + h) * height)))
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid converted bbox: {(x1, y1, x2, y2)}")
    return [x1, y1, x2, y2]


def post_predict(
    server: str,
    image_path: Path,
    sensors: list[str],
    boxes: list[list[int]],
    timeout_sec: float,
) -> dict[str, Any]:
    payload = {
        "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        "sensors": sensors,
        "boxes": boxes,
    }
    started = time.perf_counter()
    response = requests.post(
        f"{server.rstrip('/')}/predict",
        json=payload,
        timeout=timeout_sec,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    result = response.json()
    result["_client_elapsed_ms"] = elapsed_ms
    return result


def post_grounding_review(
    server: str,
    image_path: Path,
    sample: dict[str, Any],
    box: list[int],
    timeout_sec: float,
) -> dict[str, Any]:
    payload = {
        "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        "instruction": sample.get("instruction"),
        "source": REPO_ID,
        "elements": [
            {
                "id": sample.get("ui_id"),
                "label": (sample.get("action_detection") or {}).get("label"),
                "text": sample.get("instruction"),
                "category": label_value(sample.get("group")),
                "source": "screenspot-pro/action_detection",
                "box": box,
                "metadata": {
                    "application": label_value(sample.get("application")),
                    "platform": label_value(sample.get("platform")),
                    "filepath": sample.get("_hf_path"),
                },
            }
        ],
    }
    started = time.perf_counter()
    response = requests.post(
        f"{server.rstrip('/')}/grounding/review",
        json=payload,
        timeout=timeout_sec,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    result = response.json()
    result["_client_elapsed_ms"] = elapsed_ms
    return result


def draw_overlay(image_path: Path, box: list[int], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path).convert("RGB") as image:
        draw = ImageDraw.Draw(image)
        for offset in range(4):
            draw.rectangle(
                [box[0] - offset, box[1] - offset, box[2] + offset, box[3] + offset],
                outline=(255, 40, 40),
            )
        image.save(output_path)


def summarize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    detections = prediction.get("detections") or []
    first = detections[0] if detections else {}
    return {
        "sequence_text": prediction.get("sequence_text"),
        "box_source": prediction.get("box_source"),
        "latency_ms": prediction.get("latency_ms"),
        "client_elapsed_ms": prediction.get("_client_elapsed_ms"),
        "detection_count": len(detections),
        "first_key": first.get("key"),
        "first_confidence": first.get("confidence"),
        "first_sensor_keys": first.get("sensor_keys"),
        "first_fused_scores": first.get("fused_scores"),
        "fusion": prediction.get("fusion"),
    }


def summarize_grounding(grounding: dict[str, Any] | None) -> dict[str, Any] | None:
    if grounding is None:
        return None
    elements = grounding.get("elements") or []
    first = elements[0] if elements else {}
    return {
        "accepted_count": grounding.get("accepted_count"),
        "rejected_count": grounding.get("rejected_count"),
        "latency_ms": grounding.get("latency_ms"),
        "client_elapsed_ms": grounding.get("_client_elapsed_ms"),
        "first_box": first.get("box"),
        "first_area_ratio": first.get("area_ratio"),
        "first_instruction_overlap": first.get("instruction_overlap"),
        "first_crop": first.get("crop"),
    }


def markdown_report(report: dict[str, Any]) -> str:
    lines = [
        "# ScreenSpot-Pro Tiny Review",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Dataset: [`{REPO_ID}`](https://huggingface.co/datasets/{REPO_ID})",
        f"- Server: `{report['server']}`",
        f"- Sensors: `{','.join(report['sensors'])}`",
        "- Scope: tiny sample only; verifies `/grounding/review` and external `boxes` flow on non-Minecraft GUI screenshots.",
        "- It does not call any input endpoint.",
        "",
        "| UI ID | App | Platform | Instruction | Box | Grounding | Prediction | Confidence | Overlay |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for sample in report["samples"]:
        summary = sample.get("prediction_summary") or {}
        grounding = sample.get("grounding_summary") or {}
        overlay = sample.get("overlay_path", "")
        lines.append(
            "| {ui_id} | {app} | {platform} | {instruction} | {box} | {grounding} | {prediction} | {confidence} | {overlay} |".format(
                ui_id=escape_md(sample.get("ui_id", "")),
                app=escape_md(sample.get("application", "")),
                platform=escape_md(sample.get("platform", "")),
                instruction=escape_md(sample.get("instruction", "")),
                box=sample.get("box_xyxy", ""),
                grounding=escape_md(
                    f"accepted={grounding.get('accepted_count')} area={grounding.get('first_area_ratio')}"
                ),
                prediction=escape_md(str(summary.get("sequence_text", ""))),
                confidence=summary.get("first_confidence", ""),
                overlay=escape_md(overlay),
            )
        )

    lines.extend(
        [
            "",
            "Interpretation:",
            "",
            "- A/S/D/W classifier output on ScreenSpot-Pro is intentionally out-of-domain; do not read it as GUI grounding accuracy.",
            "- The useful signal is that real benchmark boxes can enter `/grounding/review` and `/predict` through external box boundaries and produce reviewable evidence without touching live input.",
            "- This is the staging point for an OmniParser/GroundCUA/ScreenSpot provider, not a baseline dependency promotion.",
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
    download_dir = args.download_dir.resolve()
    sensors = [item.strip() for item in args.sensors.split(",") if item.strip()]

    samples = download_metadata(hf_hub_download, download_dir)
    selected = choose_samples(HfApi, samples, args.max_samples)

    rows: list[dict[str, Any]] = []
    for index, sample in enumerate(selected, start=1):
        filename = str(sample["_hf_path"])
        image_path = download_image(hf_hub_download, filename, download_dir)
        with Image.open(image_path) as image:
            image_size = image.size
        box = detection_box_xyxy(sample, image_size)
        overlay_path = output_dir / "overlays" / f"{index:02d}-{Path(filename).stem}.png"
        draw_overlay(image_path, box, overlay_path)
        try:
            grounding = post_grounding_review(args.server, image_path, sample, box, args.timeout_sec)
            grounding_summary = summarize_grounding(grounding)
            grounding_error = None
        except Exception as exc:
            grounding_summary = None
            grounding_error = f"{type(exc).__name__}: {exc}"

        try:
            prediction = post_predict(args.server, image_path, sensors, [box], args.timeout_sec)
            prediction_summary = summarize_prediction(prediction)
            error = None
        except Exception as exc:
            prediction_summary = None
            error = f"{type(exc).__name__}: {exc}"

        rows.append(
            {
                "ui_id": sample.get("ui_id"),
                "filepath": filename,
                "downloaded_image": str(image_path),
                "hf_size_bytes": sample.get("_hf_size_bytes"),
                "image_size": list(image_size),
                "instruction": sample.get("instruction"),
                "application": label_value(sample.get("application")),
                "group": label_value(sample.get("group")),
                "platform": label_value(sample.get("platform")),
                "action_label": (sample.get("action_detection") or {}).get("label"),
                "box_xyxy": box,
                "overlay_path": str(overlay_path),
                "grounding_summary": grounding_summary,
                "grounding_error": grounding_error,
                "prediction_summary": prediction_summary,
                "error": error,
            }
        )

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "server": args.server,
        "repo_id": REPO_ID,
        "sensors": sensors,
        "max_samples": args.max_samples,
        "download_dir": str(download_dir),
        "samples": rows,
    }

    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    return 0


def label_value(value: Any) -> str | None:
    if isinstance(value, dict):
        label = value.get("label")
        return str(label) if label is not None else None
    return str(value) if value is not None else None


if __name__ == "__main__":
    raise SystemExit(main())
