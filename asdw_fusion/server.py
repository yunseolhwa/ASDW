from __future__ import annotations

import base64
import io
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import requests
from fastapi import FastAPI
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field

try:
    import cv2
except Exception as exc:  # pragma: no cover - import failure is reported at runtime
    cv2 = None
    CV2_IMPORT_ERROR = exc
else:
    CV2_IMPORT_ERROR = None


KEYS = ("A", "S", "D", "W")
LOGGER = logging.getLogger("asdw_fusion.server")


class PredictRequest(BaseModel):
    image_b64: str = Field(..., description="PNG/JPEG image encoded as base64.")
    sensors: list[str] | None = Field(
        default=None,
        description="Enabled sensors: template, classifier, clip, trocr, owlvit.",
    )
    debug: bool = False


class HealthResponse(BaseModel):
    ok: bool
    device: str
    sensors_loaded: list[str]
    cv2: bool
    poller: dict[str, Any] | None = None
    heartbeat: dict[str, Any] | None = None


class PollerConfig(BaseModel):
    daemon_url: str = Field(default=os.getenv("ASDW_DAEMON_URL", "http://127.0.0.1:7870"))
    interval_sec: float = Field(default=5.0, ge=0.5)
    monitor: int = Field(default=1, ge=0)
    roi: str | None = Field(default=None)
    sensors: list[str] = Field(default_factory=lambda: ["template", "classifier"])
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    dry_run: bool = False
    debug: bool = False
    press_endpoint: str = "/keys/press"
    keep_daemon_queue: bool = False
    daemon_wait: bool = True
    daemon_timeout_sec: float = Field(default=30.0, ge=0.1, le=300.0)


class PollerStatus(BaseModel):
    running: bool
    config: dict[str, Any] | None
    last_tick: dict[str, Any] | None
    tick_count: int
    last_error: str | None


class HeartbeatConfig(BaseModel):
    daemon_url: str = Field(default=os.getenv("ASDW_DAEMON_URL", "http://127.0.0.1:7870"))
    interval_sec: float = Field(default=2.0, ge=0.2)
    timeout_sec: float = Field(default=1.0, ge=0.1, le=30.0)


class HeartbeatStatus(BaseModel):
    running: bool
    online: bool
    config: dict[str, Any] | None
    last_rtt_ms: float | None
    avg_rtt_ms: float | None
    success_count: int
    failure_count: int
    last_success_at: float | None
    last_failure_at: float | None
    last_error: str | None
    last_payload: dict[str, Any] | None


@dataclass
class Detection:
    key: str
    confidence: float
    box: tuple[int, int, int, int]
    votes: dict[str, dict[str, float]]


@dataclass
class SensorVote:
    sensor: str
    scores: dict[str, float]

    @property
    def best_key(self) -> str:
        return max(self.scores, key=self.scores.get)

    @property
    def best_score(self) -> float:
        return float(self.scores[self.best_key])


class DaemonPoller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.config: PollerConfig | None = None
        self.last_tick: dict[str, Any] | None = None
        self.tick_count = 0
        self.last_error: str | None = None

    def start(self, config: PollerConfig) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._stop.set()
                self._thread.join(timeout=2)
            self._stop = threading.Event()
            self.config = config
            self.last_error = None
            self._thread = threading.Thread(target=self._run, name="asdw-daemon-poller", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        return self.status()

    def status(self) -> dict[str, Any]:
        thread = self._thread
        config = self.config.model_dump() if self.config else None
        return {
            "running": bool(thread and thread.is_alive() and not self._stop.is_set()),
            "config": config,
            "last_tick": self.last_tick,
            "tick_count": self.tick_count,
            "last_error": self.last_error,
        }

    def poll_once(self, config: PollerConfig) -> dict[str, Any]:
        return self._poll_once(config)

    def _run(self) -> None:
        while not self._stop.is_set():
            config = self.config
            if config is None:
                break
            started = time.perf_counter()
            try:
                tick = self._poll_once(config)
                with self._lock:
                    self.last_tick = tick
                    self.tick_count += 1
                    self.last_error = None
            except Exception as exc:
                LOGGER.exception("Daemon poller tick failed")
                with self._lock:
                    self.last_error = str(exc)
            elapsed = time.perf_counter() - started
            wait_sec = max(0.0, config.interval_sec - elapsed)
            self._stop.wait(wait_sec)

    def _poll_once(self, config: PollerConfig) -> dict[str, Any]:
        frame_params: dict[str, Any] = {"monitor": config.monitor}
        if config.roi:
            frame_params["roi"] = config.roi
        frame_response = requests.post(
            f"{config.daemon_url.rstrip('/')}/frame_base64",
            params=frame_params,
            timeout=10,
        )
        frame_response.raise_for_status()
        frame = frame_response.json()

        prediction = predict(
            PredictRequest(
                image_b64=str(frame["image_b64"]),
                sensors=config.sensors,
                debug=config.debug,
            )
        )
        keys = [
            str(item["key"]).upper()
            for item in prediction.get("detections", [])
            if float(item.get("confidence", 0.0)) >= config.min_confidence
        ]
        keys = [key for key in keys if key in KEYS]

        action: dict[str, Any] | None = None
        if keys:
            press_response = requests.post(
                f"{config.daemon_url.rstrip('/')}{config.press_endpoint}",
                json={
                    "keys": keys,
                    "dry_run": config.dry_run,
                    "queue": {
                        "keep_queue": config.keep_daemon_queue,
                        "wait": config.daemon_wait,
                        "timeout_sec": config.daemon_timeout_sec,
                    },
                },
                timeout=max(15.0, config.daemon_timeout_sec + 5.0),
            )
            press_response.raise_for_status()
            action = press_response.json()

        return {
            "ok": True,
            "timestamp": time.time(),
            "frame": {
                "width": frame.get("width"),
                "height": frame.get("height"),
                "roi": frame.get("roi"),
                "full_monitor": frame.get("full_monitor"),
            },
            "prediction": {
                "sequence_text": prediction.get("sequence_text"),
                "detections": prediction.get("detections", []),
                "latency_ms": prediction.get("latency_ms"),
                "device": prediction.get("device"),
            },
            "keys": keys,
            "action": action,
            "heartbeat": HEARTBEAT.status(),
        }


class HeartbeatMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.config: HeartbeatConfig | None = None
        self.last_rtt_ms: float | None = None
        self.avg_rtt_ms: float | None = None
        self.success_count = 0
        self.failure_count = 0
        self.last_success_at: float | None = None
        self.last_failure_at: float | None = None
        self.last_error: str | None = None
        self.last_payload: dict[str, Any] | None = None

    def start(self, config: HeartbeatConfig) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                self._stop.set()
                self._thread.join(timeout=2)
            self._stop = threading.Event()
            self.config = config
            self._thread = threading.Thread(target=self._run, name="asdw-heartbeat", daemon=True)
            self._thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._stop.set()
            thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2)
        return self.status()

    def status(self) -> dict[str, Any]:
        thread = self._thread
        with self._lock:
            return {
                "running": bool(thread and thread.is_alive() and not self._stop.is_set()),
                "online": self.last_success_at is not None and (
                    self.last_failure_at is None or self.last_success_at >= self.last_failure_at
                ),
                "config": self.config.model_dump() if self.config else None,
                "last_rtt_ms": self.last_rtt_ms,
                "avg_rtt_ms": self.avg_rtt_ms,
                "success_count": self.success_count,
                "failure_count": self.failure_count,
                "last_success_at": self.last_success_at,
                "last_failure_at": self.last_failure_at,
                "last_error": self.last_error,
                "last_payload": self.last_payload,
            }

    def ping_once(self, config: HeartbeatConfig) -> dict[str, Any]:
        try:
            started = time.perf_counter()
            response = requests.get(f"{config.daemon_url.rstrip('/')}/ping", timeout=config.timeout_sec)
            rtt_ms = round((time.perf_counter() - started) * 1000, 3)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            error = str(exc)
            self._record_failure(error)
            return {
                "ok": False,
                "online": False,
                "daemon_url": config.daemon_url,
                "error": error,
                "timestamp": time.time(),
            }
        self._record_success(rtt_ms, payload)
        return {
            "ok": True,
            "online": True,
            "rtt_ms": rtt_ms,
            "daemon_url": config.daemon_url,
            "payload": payload,
            "timestamp": time.time(),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            config = self.config
            if config is None:
                break
            result = self.ping_once(config)
            if not result.get("ok", False):
                LOGGER.warning("Heartbeat ping failed: %s", result.get("error"))
            self._stop.wait(config.interval_sec)

    def _record_success(self, rtt_ms: float, payload: dict[str, Any]) -> None:
        with self._lock:
            self.last_rtt_ms = rtt_ms
            self.avg_rtt_ms = rtt_ms if self.avg_rtt_ms is None else round(self.avg_rtt_ms * 0.8 + rtt_ms * 0.2, 3)
            self.success_count += 1
            self.last_success_at = time.time()
            self.last_error = None
            self.last_payload = payload

    def _record_failure(self, error: str) -> None:
        with self._lock:
            self.failure_count += 1
            self.last_failure_at = time.time()
            self.last_error = error


class ModelHub:
    def __init__(self) -> None:
        self.torch = None
        self.device = "cpu"
        self.clip_processor = None
        self.clip_model = None
        self.trocr_processor = None
        self.trocr_model = None
        self.owl_processor = None
        self.owl_model = None
        self.classifier_processor = None
        self.classifier_model = None
        self.loaded: set[str] = set()

    def ensure_torch(self) -> Any:
        if self.torch is None:
            import torch

            self.torch = torch
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            LOGGER.info("Torch device selected: %s", self.device)
        return self.torch

    def ensure_clip(self) -> None:
        if self.clip_model is not None:
            return
        torch = self.ensure_torch()
        from transformers import CLIPModel, CLIPProcessor

        model_id = os.getenv("ASDW_CLIP_MODEL", "openai/clip-vit-base-patch32")
        LOGGER.info("Loading CLIP model: %s", model_id)
        self.clip_processor = CLIPProcessor.from_pretrained(model_id)
        self.clip_model = CLIPModel.from_pretrained(model_id).to(self.device)
        self.clip_model.eval()
        if self.device == "cuda" and os.getenv("ASDW_FP16", "0") == "1":
            self.clip_model.half()
        self.loaded.add("clip")
        torch.cuda.empty_cache() if self.device == "cuda" else None

    def ensure_trocr(self) -> None:
        if self.trocr_model is not None:
            return
        self.ensure_torch()
        from transformers import TrOCRProcessor, VisionEncoderDecoderModel

        model_id = os.getenv("ASDW_TROCR_MODEL", "microsoft/trocr-small-printed")
        LOGGER.info("Loading TrOCR model: %s", model_id)
        self.trocr_processor = TrOCRProcessor.from_pretrained(model_id)
        self.trocr_model = VisionEncoderDecoderModel.from_pretrained(model_id).to(
            self.device
        )
        self.trocr_model.eval()
        self.loaded.add("trocr")

    def ensure_owlvit(self) -> None:
        if self.owl_model is not None:
            return
        self.ensure_torch()
        from transformers import OwlViTForObjectDetection, OwlViTProcessor

        model_id = os.getenv("ASDW_OWLVIT_MODEL", "google/owlvit-base-patch32")
        LOGGER.info("Loading OWL-ViT model: %s", model_id)
        self.owl_processor = OwlViTProcessor.from_pretrained(model_id)
        self.owl_model = OwlViTForObjectDetection.from_pretrained(model_id).to(
            self.device
        )
        self.owl_model.eval()
        self.loaded.add("owlvit")

    def ensure_classifier(self) -> None:
        if self.classifier_model is not None:
            return
        self.ensure_torch()
        from transformers import AutoImageProcessor, AutoModelForImageClassification

        model_id = os.getenv(
            "ASDW_CLASSIFIER_MODEL",
            "/mnt/d/asdw-fusion-typer/models/asdw-mobilenetv3-classifier/best",
        )
        LOGGER.info("Loading ASDW classifier model: %s", model_id)
        self.classifier_processor = AutoImageProcessor.from_pretrained(model_id)
        self.classifier_model = AutoModelForImageClassification.from_pretrained(model_id).to(
            self.device
        )
        self.classifier_model.eval()
        self.loaded.add("classifier")

    def classify_clip(self, image: Image.Image) -> SensorVote:
        self.ensure_clip()
        torch = self.ensure_torch()
        prompt_templates = [
            'a centered game UI button labeled "{key}"',
            'a blue video game icon with the letter "{key}"',
            'the keyboard prompt "{key}"',
        ]
        labels = []
        for key in KEYS:
            labels.extend(prompt.format(key=key) for prompt in prompt_templates)

        inputs = self.clip_processor(
            text=labels,
            images=image.convert("RGB"),
            return_tensors="pt",
            padding=True,
        )
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        if self.device == "cuda" and os.getenv("ASDW_FP16", "0") == "1":
            inputs["pixel_values"] = inputs["pixel_values"].half()
        with torch.no_grad():
            logits = self.clip_model(**inputs).logits_per_image[0].float()
        probs = logits.softmax(dim=0).detach().cpu().numpy()
        grouped: dict[str, float] = {}
        for key_index, key in enumerate(KEYS):
            start = key_index * len(prompt_templates)
            grouped[key] = float(np.max(probs[start : start + len(prompt_templates)]))
        return SensorVote("clip", normalize_scores(grouped))

    def classify_trocr(self, image: Image.Image) -> SensorVote:
        self.ensure_trocr()
        torch = self.ensure_torch()
        prepared = ImageOps.expand(image.convert("RGB"), border=12, fill=(255, 255, 255))
        pixel_values = self.trocr_processor(
            images=prepared,
            return_tensors="pt",
        ).pixel_values.to(self.device)
        with torch.no_grad():
            generated_ids = self.trocr_model.generate(
                pixel_values,
                max_new_tokens=4,
                num_beams=2,
            )
        text = self.trocr_processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0].upper()
        scores = {key: 0.05 for key in KEYS}
        for key in KEYS:
            if key in text:
                scores[key] = 0.85
                break
        return SensorVote("trocr", normalize_scores(scores))

    def detect_owlvit(self, image: Image.Image) -> list[tuple[str, float, tuple[int, int, int, int]]]:
        self.ensure_owlvit()
        torch = self.ensure_torch()
        prompts = [[f'a blue button with letter {key}' for key in KEYS]]
        inputs = self.owl_processor(
            text=prompts,
            images=image.convert("RGB"),
            return_tensors="pt",
        )
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        with torch.no_grad():
            outputs = self.owl_model(**inputs)
        target_sizes = torch.tensor([image.size[::-1]], device=self.device)
        results = self.owl_processor.post_process_object_detection(
            outputs=outputs,
            threshold=float(os.getenv("ASDW_OWLVIT_THRESHOLD", "0.05")),
            target_sizes=target_sizes,
        )[0]
        detections = []
        for score, label, box in zip(
            results["scores"], results["labels"], results["boxes"], strict=False
        ):
            label_index = int(label.detach().cpu())
            if label_index < len(KEYS):
                x1, y1, x2, y2 = [int(round(v)) for v in box.detach().cpu().tolist()]
                detections.append((KEYS[label_index], float(score.detach().cpu()), (x1, y1, x2, y2)))
        return detections

    def classify_asdw(self, image: Image.Image) -> SensorVote:
        self.ensure_classifier()
        torch = self.ensure_torch()
        prepared = normalize_classifier_crop(image)
        inputs = self.classifier_processor(images=[prepared], return_tensors="pt")
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        with torch.no_grad():
            logits = self.classifier_model(**inputs).logits[0].float()
        probs = logits.softmax(dim=0).detach().cpu().numpy()
        id2label = self.classifier_model.config.id2label
        scores = {key: 0.0 for key in KEYS}
        for index, probability in enumerate(probs):
            label = str(id2label.get(index, index)).upper()
            if label in scores:
                scores[label] = float(probability)
        return SensorVote("classifier", normalize_scores(scores))


MODEL_HUB = ModelHub()
HEARTBEAT = HeartbeatMonitor()
POLLER = DaemonPoller()
app = FastAPI(title="ASDW Fusion Typer", version="0.1.0")


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        MODEL_HUB.ensure_torch()
    except Exception:
        device = "unknown"
    else:
        device = MODEL_HUB.device
    return HealthResponse(
        ok=True,
        device=device,
        sensors_loaded=sorted(MODEL_HUB.loaded),
        cv2=cv2 is not None,
        poller=POLLER.status(),
        heartbeat=HEARTBEAT.status(),
    )


@app.get("/heartbeat/status", response_model=HeartbeatStatus)
def heartbeat_status() -> dict[str, Any]:
    return HEARTBEAT.status()


@app.post("/heartbeat/start", response_model=HeartbeatStatus)
def heartbeat_start(config: HeartbeatConfig) -> dict[str, Any]:
    return HEARTBEAT.start(config)


@app.post("/heartbeat/stop", response_model=HeartbeatStatus)
def heartbeat_stop() -> dict[str, Any]:
    return HEARTBEAT.stop()


@app.post("/heartbeat/ping_once")
def heartbeat_ping_once(config: HeartbeatConfig) -> dict[str, Any]:
    return HEARTBEAT.ping_once(config)


@app.get("/poller/status", response_model=PollerStatus)
def poller_status() -> dict[str, Any]:
    return POLLER.status()


@app.post("/poller/start", response_model=PollerStatus)
def poller_start(config: PollerConfig) -> dict[str, Any]:
    return POLLER.start(config)


@app.post("/poller/stop", response_model=PollerStatus)
def poller_stop() -> dict[str, Any]:
    return POLLER.stop()


@app.post("/poller/tick")
def poller_tick(config: PollerConfig) -> dict[str, Any]:
    tick = POLLER.poll_once(config)
    with POLLER._lock:
        POLLER.last_tick = tick
        POLLER.tick_count += 1
        POLLER.last_error = None
    return tick


@app.post("/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    started = time.perf_counter()
    image = decode_image(request.image_b64)
    sensors = normalize_sensor_list(request.sensors)

    boxes = find_button_boxes(image)
    owl_detections = MODEL_HUB.detect_owlvit(image) if "owlvit" in sensors else []
    if not boxes and owl_detections:
        boxes = [box for _, _, box in owl_detections]

    detections: list[Detection] = []
    for box in boxes:
        crop = crop_with_margin(image, box, margin=0.18)
        votes = classify_crop(crop, sensors)
        add_owl_votes(votes, box, owl_detections)
        key, confidence = fuse_votes(votes)
        detections.append(Detection(key=key, confidence=confidence, box=box, votes=votes))

    detections.sort(key=lambda item: item.box[0])
    sequence = [item.key for item in detections if item.confidence >= 0.30]
    response: dict[str, Any] = {
        "sequence": sequence,
        "sequence_text": "".join(sequence),
        "detections": [
            {
                "key": item.key,
                "confidence": round(item.confidence, 4),
                "box": item.box,
                "votes": item.votes,
            }
            for item in detections
        ],
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "sensors": sensors,
        "device": MODEL_HUB.device,
    }
    if request.debug:
        response["debug"] = {
            "image_size": image.size,
            "candidate_count": len(boxes),
            "owlvit": [
                {"key": key, "confidence": score, "box": box}
                for key, score, box in owl_detections
            ],
        }
    return response


def normalize_sensor_list(sensors: list[str] | None) -> list[str]:
    if not sensors:
        raw = os.getenv("ASDW_SENSORS", "template,clip")
        sensors = [item.strip() for item in raw.split(",") if item.strip()]
    allowed = {"template", "classifier", "clip", "trocr", "owlvit"}
    selected = [sensor.lower() for sensor in sensors if sensor.lower() in allowed]
    return selected or ["template"]


def decode_image(image_b64: str) -> Image.Image:
    if "," in image_b64 and image_b64.lstrip().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    data = base64.b64decode(image_b64)
    return Image.open(io.BytesIO(data)).convert("RGB")


def find_button_boxes(image: Image.Image) -> list[tuple[int, int, int, int]]:
    if cv2 is None:
        raise RuntimeError(f"opencv-python-headless is required: {CV2_IMPORT_ERROR}")
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)

    lower_blue = np.array([85, 45, 45], dtype=np.uint8)
    upper_blue = np.array([135, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower_blue, upper_blue)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.dilate(mask, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    min_area = max(90, int(width * height * 0.0008))
    max_area = int(width * height * 0.18)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        aspect = w / max(h, 1)
        if aspect > 2.4 and h >= 18 and area >= min_area:
            boxes.extend(split_wide_mask_box(mask, (x, y, x + w, y + h)))
            continue
        if area < min_area or area > max_area:
            continue
        if w < 18 or h < 18:
            continue
        if not 0.55 <= aspect <= 1.70:
            continue
        fill_ratio = area / max(w * h, 1)
        if fill_ratio < 0.12:
            continue
        boxes.append((x, y, x + w, y + h))

    boxes = merge_boxes(boxes)
    return keep_primary_horizontal_row(boxes, image.size)


def split_wide_mask_box(
    mask: np.ndarray,
    box: tuple[int, int, int, int],
) -> list[tuple[int, int, int, int]]:
    if cv2 is None:
        return []
    x1, y1, x2, y2 = box
    roi = mask[y1:y2, x1:x2]
    if roi.size == 0:
        return []
    col = (roi > 0).sum(axis=0).astype(np.float32)
    col = cv2.GaussianBlur(col.reshape(1, -1), (1, 9), 0).ravel()
    if float(col.max()) <= 0:
        return []
    threshold = float(col.max()) * 0.30
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(col):
        if value > threshold and start is None:
            start = index
        is_last = index == len(col) - 1
        if start is not None and (value <= threshold or is_last):
            end = index if value <= threshold else index + 1
            if end - start >= max(12, int((y2 - y1) * 0.45)):
                segments.append((start, end))
            start = None
    split_boxes = []
    for start, end in segments:
        width = end - start
        height = y2 - y1
        if 0.45 <= width / max(height, 1) <= 1.45:
            split_boxes.append((x1 + start, y1, x1 + end, y2))
    return split_boxes


def merge_boxes(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    merged: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda item: (item[0], item[1])):
        matched = False
        for index, existing in enumerate(merged):
            if box_iou(box, existing) > 0.20 or close_centers(box, existing):
                merged[index] = (
                    min(existing[0], box[0]),
                    min(existing[1], box[1]),
                    max(existing[2], box[2]),
                    max(existing[3], box[3]),
                )
                matched = True
                break
        if not matched:
            merged.append(box)
    return merged


def close_centers(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    ax, ay = box_center(a)
    bx, by = box_center(b)
    aw, ah = a[2] - a[0], a[3] - a[1]
    bw, bh = b[2] - b[0], b[3] - b[1]
    return abs(ax - bx) < max(aw, bw) * 0.35 and abs(ay - by) < max(ah, bh) * 0.45


def keep_primary_horizontal_row(
    boxes: list[tuple[int, int, int, int]],
    image_size: tuple[int, int],
) -> list[tuple[int, int, int, int]]:
    if len(boxes) <= 1:
        return sorted(boxes, key=lambda item: item[0])
    width, height = image_size
    center_x = width / 2
    center_y = height / 2
    boxes = [
        box
        for box in boxes
        if abs(box_center(box)[0] - center_x) < width * 0.48
        and abs(box_center(box)[1] - center_y) < height * 0.48
    ]
    if len(boxes) <= 1:
        return sorted(boxes, key=lambda item: item[0])

    groups: list[list[tuple[int, int, int, int]]] = []
    for box in sorted(boxes, key=lambda item: box_center(item)[1]):
        _, cy = box_center(box)
        placed = False
        for group in groups:
            median_height = np.median([member[3] - member[1] for member in group])
            group_y = np.median([box_center(member)[1] for member in group])
            if abs(cy - group_y) <= max(14, median_height * 0.45):
                group.append(box)
                placed = True
                break
        if not placed:
            groups.append([box])

    def group_score(group: list[tuple[int, int, int, int]]) -> float:
        count = len(group)
        area = sum((box[2] - box[0]) * (box[3] - box[1]) for box in group)
        y_distance = abs(np.mean([box_center(box)[1] for box in group]) - center_y)
        return count * 1000 + area * 0.01 - y_distance

    best = max(groups, key=group_score)
    return sorted(best, key=lambda item: item[0])


def crop_with_margin(
    image: Image.Image,
    box: tuple[int, int, int, int],
    margin: float,
) -> Image.Image:
    x1, y1, x2, y2 = box
    width, height = image.size
    pad_x = int(round((x2 - x1) * margin))
    pad_y = int(round((y2 - y1) * margin))
    return image.crop(
        (
            max(0, x1 - pad_x),
            max(0, y1 - pad_y),
            min(width, x2 + pad_x),
            min(height, y2 + pad_y),
        )
    )


def normalize_classifier_crop(image: Image.Image, size: int = 112) -> Image.Image:
    image = image.convert("RGB")
    side = max(image.size)
    canvas = Image.new("RGB", (side, side), (32, 24, 28))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas.resize((size, size), Image.Resampling.BICUBIC)


def classify_crop(crop: Image.Image, sensors: list[str]) -> dict[str, dict[str, float]]:
    votes: dict[str, dict[str, float]] = {}
    if "template" in sensors:
        votes["template"] = template_scores(crop)
    if "classifier" in sensors:
        votes["classifier"] = MODEL_HUB.classify_asdw(crop).scores
    if "clip" in sensors:
        votes["clip"] = MODEL_HUB.classify_clip(crop).scores
    if "trocr" in sensors:
        votes["trocr"] = MODEL_HUB.classify_trocr(crop).scores
    return votes


def add_owl_votes(
    votes: dict[str, dict[str, float]],
    box: tuple[int, int, int, int],
    owl_detections: list[tuple[str, float, tuple[int, int, int, int]]],
) -> None:
    if not owl_detections:
        return
    scores = {key: 0.01 for key in KEYS}
    for key, score, owl_box in owl_detections:
        overlap = box_iou(box, owl_box)
        if overlap > 0.05:
            scores[key] = max(scores[key], float(score) * min(1.0, overlap * 2.0))
    votes["owlvit"] = normalize_scores(scores)


def fuse_votes(votes: dict[str, dict[str, float]]) -> tuple[str, float]:
    weights = {
        "template": float(os.getenv("ASDW_WEIGHT_TEMPLATE", "0.35")),
        "classifier": float(os.getenv("ASDW_WEIGHT_CLASSIFIER", "1.25")),
        "clip": float(os.getenv("ASDW_WEIGHT_CLIP", "1.00")),
        "trocr": float(os.getenv("ASDW_WEIGHT_TROCR", "1.10")),
        "owlvit": float(os.getenv("ASDW_WEIGHT_OWLVIT", "0.50")),
    }
    fused = {key: 0.0 for key in KEYS}
    total_weight = 0.0
    for sensor, scores in votes.items():
        weight = weights.get(sensor, 1.0)
        total_weight += weight
        for key in KEYS:
            fused[key] += weight * float(scores.get(key, 0.0))
    if total_weight <= 0:
        return "?", 0.0
    fused = {key: value / total_weight for key, value in fused.items()}
    best_key = max(fused, key=fused.get)
    sorted_scores = sorted(fused.values(), reverse=True)
    margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
    confidence = max(0.0, min(1.0, sorted_scores[0] * 0.75 + margin * 0.50))
    return best_key, float(confidence)


def normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    values = np.array([max(float(scores.get(key, 0.0)), 1e-6) for key in KEYS], dtype=np.float32)
    values = values / max(float(values.sum()), 1e-6)
    return {key: float(value) for key, value in zip(KEYS, values, strict=True)}


@lru_cache(maxsize=1)
def rendered_templates() -> dict[str, np.ndarray]:
    templates = {}
    for key in KEYS:
        templates[key] = render_letter_mask(key)
    return templates


def render_letter_mask(key: str) -> np.ndarray:
    size = 64
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    font = load_font(46)
    bbox = draw.textbbox((0, 0), key, font=font)
    x = (size - (bbox[2] - bbox[0])) // 2 - bbox[0]
    y = (size - (bbox[3] - bbox[1])) // 2 - bbox[1]
    draw.text((x, y), key, font=font, fill=255)
    return normalize_mask(np.asarray(image) > 0)


def load_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def template_scores(image: Image.Image) -> dict[str, float]:
    observed = extract_letter_mask(image)
    if observed is None:
        return {key: 1.0 / len(KEYS) for key in KEYS}
    scores = {}
    for key, template in rendered_templates().items():
        scores[key] = mask_similarity(observed, template)
    minimum = min(scores.values())
    shifted = {key: value - minimum + 1e-3 for key, value in scores.items()}
    return normalize_scores(shifted)


def extract_letter_mask(image: Image.Image) -> np.ndarray | None:
    if cv2 is None:
        return None
    arr = np.asarray(image.convert("RGB"))
    height, width = arr.shape[:2]
    y1, y2 = int(height * 0.15), int(height * 0.85)
    x1, x2 = int(width * 0.15), int(width * 0.85)
    inner = arr[y1:y2, x1:x2]
    if inner.size == 0:
        return None
    gray = cv2.cvtColor(inner, cv2.COLOR_RGB2GRAY)
    _, bright = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    hsv = cv2.cvtColor(inner, cv2.COLOR_RGB2HSV)
    low_sat_bright = cv2.inRange(hsv, np.array([0, 0, 155]), np.array([179, 85, 255]))
    mask = cv2.bitwise_or(bright, low_sat_bright)
    mask = cv2.medianBlur(mask, 3)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    candidate_points = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area >= 4 and h >= inner.shape[0] * 0.12:
            candidate_points.append((x, y, x + w, y + h))
    if not candidate_points:
        return None
    x_min = max(0, min(item[0] for item in candidate_points) - 2)
    y_min = max(0, min(item[1] for item in candidate_points) - 2)
    x_max = min(mask.shape[1], max(item[2] for item in candidate_points) + 2)
    y_max = min(mask.shape[0], max(item[3] for item in candidate_points) + 2)
    glyph = mask[y_min:y_max, x_min:x_max] > 0
    return normalize_mask(glyph)


def normalize_mask(mask: np.ndarray, size: int = 48) -> np.ndarray:
    if cv2 is None:
        return mask.astype(np.float32)
    mask_uint8 = (mask.astype(np.uint8) * 255)
    ys, xs = np.where(mask_uint8 > 0)
    canvas = np.zeros((size, size), dtype=np.uint8)
    if len(xs) == 0 or len(ys) == 0:
        return canvas.astype(np.float32)
    glyph = mask_uint8[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h, w = glyph.shape[:2]
    scale = min((size - 6) / max(w, 1), (size - 6) / max(h, 1))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(glyph, (new_w, new_h), interpolation=cv2.INTER_AREA)
    x = (size - new_w) // 2
    y = (size - new_h) // 2
    canvas[y : y + new_h, x : x + new_w] = resized
    return (canvas.astype(np.float32) / 255.0)


def mask_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    if a.shape != b.shape and cv2 is not None:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    a = a - float(a.mean())
    b = b - float(b.mean())
    denom = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    if denom <= 1e-6:
        return 0.0
    return float((a * b).sum() / denom)


def box_center(box: tuple[int, int, int, int]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def box_iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - intersection
    return intersection / union if union else 0.0


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=os.getenv("ASDW_LOG_LEVEL", "INFO"))
    uvicorn.run(
        "asdw_fusion.server:app",
        host=os.getenv("ASDW_HOST", "0.0.0.0"),
        port=int(os.getenv("ASDW_PORT", "7868")),
        reload=False,
    )
