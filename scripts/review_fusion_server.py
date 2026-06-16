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
DEFAULT_OUTPUT_DIR = Path("artifacts/fusion-review/latest")
DEFAULT_DATASET_LABELS = Path("artifacts/captcha-tiles/captcha_tiles_800x600/labels.json")
BASELINE_SENSOR_SETS = [
    ("template",),
    ("classifier",),
    ("template", "classifier"),
]
CANDIDATE_SENSOR_SETS = [
    ("clip",),
    ("trocr",),
    ("owlvit",),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a review report from the existing ASDW fusion server APIs.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868", help="Fusion server base URL.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE, help="Image to send to /predict.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Report output directory.")
    parser.add_argument("--expected-sequence", default="SDWWDWDAA", help="Expected sequence for the default review sample.")
    parser.add_argument(
        "--include-candidates",
        action="store_true",
        help="Also test CLIP, TrOCR, and OWL-ViT candidate sensors. This can be slow.",
    )
    parser.add_argument("--timeout-sec", type=float, default=300.0, help="HTTP timeout per request.")
    parser.add_argument(
        "--dataset-labels",
        type=Path,
        default=None,
        help=f"Optional labels.json for dataset evaluation, for example {DEFAULT_DATASET_LABELS}.",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Directory containing dataset images. Defaults to the labels file parent.",
    )
    parser.add_argument(
        "--dataset-sensors",
        default="template,classifier",
        help="Comma-separated sensors for dataset evaluation.",
    )
    parser.add_argument(
        "--max-dataset-samples",
        type=int,
        default=20,
        help="Maximum dataset samples to evaluate when --dataset-labels is set.",
    )
    parser.add_argument(
        "--dataset-use-label-boxes",
        action="store_true",
        help="Pass labels.json bboxes to /predict as external boxes for classifier/fusion review.",
    )
    return parser.parse_args()


def post_predict(
    server: str,
    image_b64: str,
    sensors: tuple[str, ...],
    timeout_sec: float,
    boxes: list[list[int]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload: dict[str, Any] = {"image_b64": image_b64, "sensors": list(sensors)}
    if boxes is not None:
        payload["boxes"] = boxes
    response = requests.post(
        f"{server.rstrip('/')}/predict",
        json=payload,
        timeout=timeout_sec,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    payload = response.json()
    payload["_client_elapsed_ms"] = elapsed_ms
    return payload


def summarize_prediction(
    sensors: tuple[str, ...],
    prediction: dict[str, Any],
    expected_sequence: str,
) -> dict[str, Any]:
    detections = prediction.get("detections") or []
    fusion = prediction.get("fusion") or {}
    sequence_text = prediction.get("sequence_text") or ""
    return {
        "sensors": list(sensors),
        "sequence_text": sequence_text,
        "expected_sequence": expected_sequence,
        "matches_expected": bool(expected_sequence) and sequence_text == expected_sequence,
        "latency_ms": prediction.get("latency_ms"),
        "client_elapsed_ms": prediction.get("_client_elapsed_ms"),
        "detections": len(detections),
        "device": prediction.get("device"),
        "box_source": prediction.get("box_source"),
        "accepted_count": fusion.get("accepted_count"),
        "rejected_count": fusion.get("rejected_count"),
        "agreement_rate": fusion.get("agreement_rate"),
        "sensor_sequences": fusion.get("sensor_sequences"),
        "disagreement_count": len(fusion.get("disagreements") or []),
    }


def evaluate_dataset(
    server: str,
    labels_path: Path,
    dataset_root: Path,
    sensors: tuple[str, ...],
    max_samples: int,
    timeout_sec: float,
    use_label_boxes: bool,
) -> dict[str, Any]:
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    if max_samples > 0:
        labels = labels[:max_samples]

    sample_results: list[dict[str, Any]] = []
    sequence_correct = 0
    detection_count_matches = 0
    latencies: list[float] = []
    for row in labels:
        image_path = dataset_root / row["file"]
        expected_sequence = str(row["sequence"])
        expected_count = len(row.get("objects") or expected_sequence)
        try:
            image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
            boxes = None
            if use_label_boxes:
                boxes = [obj["bbox_xyxy"] for obj in row.get("objects", [])]
            prediction = post_predict(server, image_b64, sensors, timeout_sec, boxes=boxes)
            summary = summarize_prediction(sensors, prediction, expected_sequence)
            summary["id"] = row.get("id")
            summary["file"] = row.get("file")
            summary["expected_count"] = expected_count
            sequence_correct += int(bool(summary.get("matches_expected")))
            detection_count_matches += int(summary.get("detections") == expected_count)
            if isinstance(summary.get("latency_ms"), (int, float)):
                latencies.append(float(summary["latency_ms"]))
        except Exception as exc:
            summary = {
                "id": row.get("id"),
                "file": row.get("file"),
                "sensors": list(sensors),
                "expected_sequence": expected_sequence,
                "sequence_text": "",
                "matches_expected": False,
                "expected_count": expected_count,
                "error": str(exc),
            }
        sample_results.append(summary)

    sample_count = len(sample_results)
    return {
        "labels": str(labels_path),
        "root": str(dataset_root),
        "sensors": list(sensors),
        "box_source": "label_boxes" if use_label_boxes else "builtin_detector",
        "samples": sample_count,
        "sequence_correct": sequence_correct,
        "sequence_accuracy": round(sequence_correct / sample_count, 4) if sample_count else 0.0,
        "detection_count_matches": detection_count_matches,
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "sample_results": sample_results,
    }


def markdown_report(report: dict[str, Any]) -> str:
    rows = []
    for item in report["predictions"]:
        status = "PASS" if item.get("matches_expected") else "CHECK"
        if item.get("error"):
            status = "ERROR"
        rows.append(
            "| {sensors} | {sequence} | {detections} | {latency} | {agreement} | {status} |".format(
                sensors=",".join(item.get("sensors", [])),
                sequence=item.get("sequence_text", ""),
                detections=item.get("detections", ""),
                latency=item.get("latency_ms", ""),
                agreement=item.get("agreement_rate", ""),
                status=status,
            )
        )

    lines = [
        "# Fusion Server Review Report",
        "",
        f"- Generated at local: `{report['generated_at_local']}`",
        f"- Generated at UTC: `{report['generated_at_utc']}`",
        f"- Server: `{report['server']}`",
        f"- Image: `{report['image']}`",
        f"- Expected sequence: `{report['expected_sequence']}`",
        f"- Server device: `{report.get('status', {}).get('device', 'unknown')}`",
        f"- Loaded sensors: `{', '.join(report.get('status', {}).get('loaded_sensors', []))}`",
        "",
        "| Sensors | Sequence | Detections | Latency ms | Agreement | Status |",
        "| --- | --- | ---: | ---: | ---: | --- |",
        *rows,
    ]

    dataset = report.get("dataset_evaluation")
    if dataset:
        lines.extend(
            [
                "",
                "## Dataset Evaluation",
                "",
                f"- Labels: `{dataset['labels']}`",
                f"- Sensors: `{','.join(dataset['sensors'])}`",
                f"- Box source: `{dataset['box_source']}`",
                f"- Samples: `{dataset['samples']}`",
                f"- Sequence accuracy: `{dataset['sequence_correct']}/{dataset['samples']} = {dataset['sequence_accuracy']}`",
                f"- Exact detection count: `{dataset['detection_count_matches']}/{dataset['samples']}`",
                f"- Average latency ms: `{dataset['avg_latency_ms']}`",
                "",
                "| ID | Expected | Predicted | Detections | Latency ms | Status |",
                "| ---: | --- | --- | ---: | ---: | --- |",
            ]
        )
        for sample in dataset.get("sample_results", [])[:20]:
            status = "PASS" if sample.get("matches_expected") else "CHECK"
            if sample.get("error"):
                status = "ERROR"
            lines.append(
                "| {id} | {expected} | {predicted} | {detections} | {latency} | {status} |".format(
                    id=sample.get("id", ""),
                    expected=sample.get("expected_sequence", ""),
                    predicted=sample.get("sequence_text", ""),
                    detections=sample.get("detections", ""),
                    latency=sample.get("latency_ms", ""),
                    status=status,
                )
            )

    lines.extend(
        [
            "",
            "Notes:",
            "",
            "- This script only calls `/fusion/status` and `/predict`; it does not call input endpoints.",
            "- Candidate sensors are review smoke checks, not baseline promotion evidence.",
            "- Dataset evaluation uses existing labeled artifacts and does not retrain models.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    image_path = args.image.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    sensor_sets = list(BASELINE_SENSOR_SETS)
    if args.include_candidates:
        sensor_sets.extend(CANDIDATE_SENSOR_SETS)

    response = requests.get(f"{args.server.rstrip('/')}/fusion/status", timeout=args.timeout_sec)
    response.raise_for_status()
    initial_status = response.json()

    predictions: list[dict[str, Any]] = []
    for sensors in sensor_sets:
        try:
            prediction = post_predict(args.server, image_b64, sensors, args.timeout_sec)
            summary = summarize_prediction(sensors, prediction, args.expected_sequence)
        except Exception as exc:
            summary = {
                "sensors": list(sensors),
                "sequence_text": "",
                "expected_sequence": args.expected_sequence,
                "matches_expected": False,
                "error": str(exc),
            }
        predictions.append(summary)

    dataset_evaluation = None
    if args.dataset_labels:
        labels_path = args.dataset_labels.resolve()
        dataset_root = args.dataset_root.resolve() if args.dataset_root else labels_path.parent
        dataset_sensors = tuple(item.strip() for item in args.dataset_sensors.split(",") if item.strip())
        dataset_evaluation = evaluate_dataset(
            args.server,
            labels_path,
            dataset_root,
            dataset_sensors,
            args.max_dataset_samples,
            args.timeout_sec,
            args.dataset_use_label_boxes,
        )

    try:
        response = requests.get(f"{args.server.rstrip('/')}/fusion/status", timeout=args.timeout_sec)
        response.raise_for_status()
        final_status = response.json()
    except Exception:
        final_status = initial_status

    generated_at_utc = datetime.now(timezone.utc)
    generated_at_local = generated_at_utc.astimezone()
    report = {
        "generated_at": generated_at_local.isoformat(),
        "generated_at_local": generated_at_local.isoformat(),
        "generated_at_utc": generated_at_utc.isoformat(),
        "server": args.server,
        "image": str(image_path),
        "expected_sequence": args.expected_sequence,
        "initial_status": initial_status,
        "status": final_status,
        "predictions": predictions,
        "dataset_evaluation": dataset_evaluation,
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
