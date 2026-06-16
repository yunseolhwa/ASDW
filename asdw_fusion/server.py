from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import numpy as np
import requests
from fastapi import FastAPI
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

try:
    import cv2
except Exception as exc:  # pragma: no cover - import failure is reported at runtime
    cv2 = None
    CV2_IMPORT_ERROR = exc
else:
    CV2_IMPORT_ERROR = None


KEYS = ("A", "S", "D", "W")
LOGGER = logging.getLogger("asdw_fusion.server")
DEFAULT_DAEMON_URL = "http://127.0.0.1:7870"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_LLM_MODEL = "Qwen/Qwen2.5-3B-Instruct"
ACTIONABLE_AGENT_ACTIONS = {"press_sequence", "type_text"}
FUSION_SENSORS = ("template", "classifier", "clip", "trocr", "owlvit")
BASELINE_FUSION_SENSORS = ("template", "classifier")
CANDIDATE_FUSION_SENSORS = ("clip", "trocr", "owlvit")
DEFAULT_SEQUENCE_MIN_CONFIDENCE = 0.30
SENSOR_ROLES = {
    "template": {
        "tier": "baseline",
        "role": "fast OpenCV reference sensor",
        "promotion": "verified for review sample, but not strong enough alone",
    },
    "classifier": {
        "tier": "baseline",
        "role": "local Hugging Face image-classification sensor",
        "promotion": "primary ASDW classifier for the current baseline",
    },
    "clip": {
        "tier": "candidate",
        "role": "zero-shot image-text comparison sensor",
        "promotion": "requires runtime and accuracy verification before baseline use",
    },
    "trocr": {
        "tier": "candidate",
        "role": "OCR sensor for text-like prompts",
        "promotion": "requires runtime and latency verification before baseline use",
    },
    "owlvit": {
        "tier": "candidate",
        "role": "open-vocabulary detection sensor",
        "promotion": "requires target localization verification before baseline use",
    },
}


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class PredictRequest(BaseModel):
    image_b64: str = Field(..., description="PNG/JPEG image encoded as base64.")
    sensors: list[str] | None = Field(
        default=None,
        description="Enabled sensors: template, classifier, clip, trocr, owlvit.",
    )
    boxes: list[tuple[int, int, int, int]] | None = Field(
        default=None,
        description="Optional external xyxy boxes. When provided, /predict skips built-in box detection.",
    )
    debug: bool = False

    @field_validator("boxes", mode="before")
    @classmethod
    def normalize_boxes_payload(cls, boxes: Any) -> Any:
        if boxes is None:
            return None
        if isinstance(boxes, list) and boxes and all(not isinstance(item, (list, tuple)) for item in boxes):
            if len(boxes) % 4 != 0:
                raise ValueError("flat boxes must contain a multiple of four numbers")
            return [boxes[index : index + 4] for index in range(0, len(boxes), 4)]
        return boxes


class GroundingElementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    box: tuple[int, int, int, int] = Field(..., description="Element bbox in xyxy pixel coordinates.")
    id: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", "label", "text", "category", "source")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class GroundingReviewRequest(BaseModel):
    image_b64: str = Field(..., description="PNG/JPEG image encoded as base64.")
    instruction: str | None = Field(default=None, max_length=1000)
    source: str = Field(default="external", max_length=200)
    elements: list[GroundingElementInput] = Field(default_factory=list)
    debug: bool = False

    @field_validator("instruction", "source")
    @classmethod
    def normalize_text_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class HealthResponse(BaseModel):
    ok: bool
    device: str
    sensors_loaded: list[str]
    cv2: bool
    poller: dict[str, Any] | None = None
    heartbeat: dict[str, Any] | None = None


class PollerConfig(BaseModel):
    daemon_url: str = Field(default=os.getenv("ASDW_DAEMON_URL", DEFAULT_DAEMON_URL))
    interval_sec: float = Field(default=5.0, ge=0.5)
    monitor: int = Field(default=1, ge=0)
    roi: str | None = Field(default=None)
    capture_provider: Literal["mss", "dxcam", "windows_capture"] = "mss"
    target_id: str | None = Field(default=None)
    sensors: list[str] = Field(default_factory=lambda: ["template", "classifier"])
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    dry_run: bool = False
    debug: bool = False
    input_provider: Literal["builtin", "pydirectinput"] = "builtin"
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
    daemon_url: str = Field(default=os.getenv("ASDW_DAEMON_URL", DEFAULT_DAEMON_URL))
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


class LLMConfig(BaseModel):
    base_url: str = Field(default_factory=lambda: os.getenv("ASDW_LLM_BASE_URL", DEFAULT_LLM_BASE_URL))
    model: str = Field(default_factory=lambda: os.getenv("ASDW_LLM_MODEL", DEFAULT_LLM_MODEL))
    timeout_sec: float = Field(default_factory=lambda: env_float("ASDW_LLM_TIMEOUT_SEC", 20.0), ge=0.1, le=300.0)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=384, ge=64, le=4096)


class LLMCheckConfig(LLMConfig):
    timeout_sec: float = Field(default_factory=lambda: env_float("ASDW_LLM_CHECK_TIMEOUT_SEC", 2.0), ge=0.1, le=30.0)


class AgentActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["idle", "captcha_prompt", "typing_prompt", "blocked", "unknown", "error"]
    action: Literal["none", "press_sequence", "type_text", "retry_capture", "stop"]
    keys: list[str] = Field(default_factory=list)
    text: str | None = Field(default=None, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("keys")
    @classmethod
    def normalize_keys(cls, keys: list[str]) -> list[str]:
        normalized = [str(key).upper() for key in keys]
        invalid = [key for key in normalized if key not in KEYS]
        if invalid:
            raise ValueError(f"keys must contain only A/S/D/W: {invalid}")
        return normalized

    @field_validator("text")
    @classmethod
    def normalize_text(cls, text: str | None) -> str | None:
        if text is None:
            return None
        text = text.strip()
        return text or None

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, reason: str) -> str:
        return reason.strip()

    @model_validator(mode="after")
    def validate_action_payload(self) -> "AgentActionDecision":
        if self.action == "press_sequence":
            if not self.keys:
                raise ValueError("press_sequence requires non-empty keys")
            if self.text is not None:
                raise ValueError("press_sequence must not include text")
        elif self.action == "type_text":
            if not self.text:
                raise ValueError("type_text requires text")
            if self.keys:
                raise ValueError("type_text must not include keys")
        else:
            if self.keys:
                raise ValueError(f"{self.action} must not include keys")
            if self.text is not None:
                raise ValueError(f"{self.action} must not include text")
        return self


class AgentStepRequest(BaseModel):
    daemon_url: str = Field(default_factory=lambda: os.getenv("ASDW_DAEMON_URL", DEFAULT_DAEMON_URL))
    monitor: int = Field(default=1, ge=0)
    roi: str | None = Field(default=None)
    capture_provider: Literal["mss", "dxcam", "windows_capture"] = "mss"
    target_id: str | None = Field(default=None)
    sensors: list[str] = Field(default_factory=lambda: ["template", "classifier"])
    debug: bool = False
    mode: Literal["observe", "rehearse", "live"] = "observe"
    context: dict[str, Any] = Field(default_factory=dict)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    min_action_confidence: float = Field(
        default_factory=lambda: env_float("ASDW_AGENT_MIN_CONFIDENCE", 0.60),
        ge=0.0,
        le=1.0,
    )


class AgentActRequest(AgentStepRequest):
    allow_live_input: bool = False
    decision: AgentActionDecision | None = None
    input_provider: Literal["builtin", "pydirectinput"] = "builtin"
    keep_daemon_queue: bool = False
    daemon_wait: bool = True
    daemon_timeout_sec: float = Field(default=30.0, ge=0.1, le=300.0)


@dataclass
class Detection:
    key: str
    confidence: float
    box: tuple[int, int, int, int]
    votes: dict[str, dict[str, float]]
    fused_scores: dict[str, float]


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
        frame_params: dict[str, Any] = {"monitor": config.monitor, "provider": config.capture_provider}
        if config.roi:
            frame_params["roi"] = config.roi
        if config.target_id:
            frame_params["target_id"] = config.target_id
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
                    "provider": config.input_provider,
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
                "provider": frame.get("provider"),
                "target": frame.get("target"),
                "region": frame.get("region"),
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


class AgentRuntimeState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.mode: Literal["observe", "rehearse", "live"] = "observe"
        self.last_step: dict[str, Any] | None = None
        self.last_act: dict[str, Any] | None = None

    def record_step(self, mode: Literal["observe", "rehearse", "live"], result: dict[str, Any]) -> None:
        with self._lock:
            self.mode = mode
            self.last_step = result

    def record_act(self, mode: Literal["observe", "rehearse", "live"], result: dict[str, Any]) -> None:
        with self._lock:
            self.mode = mode
            self.last_act = result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mode": self.mode,
                "last_step": self.last_step,
                "last_act": self.last_act,
            }


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
        prompt_labels = [f"a blue button with letter {key}" for key in KEYS]
        prompts = [prompt_labels]
        inputs = self.owl_processor(
            text=prompts,
            images=image.convert("RGB"),
            return_tensors="pt",
        )
        inputs = {name: value.to(self.device) for name, value in inputs.items()}
        with torch.no_grad():
            outputs = self.owl_model(**inputs)
        target_sizes = torch.tensor([image.size[::-1]], device=self.device)
        threshold = float(os.getenv("ASDW_OWLVIT_THRESHOLD", "0.05"))
        post_process = getattr(self.owl_processor, "post_process_object_detection", None)
        if post_process is None:
            post_process = self.owl_processor.post_process_grounded_object_detection
            results = post_process(
                outputs=outputs,
                threshold=threshold,
                target_sizes=target_sizes,
                text_labels=prompts,
            )[0]
        else:
            results = post_process(
                outputs=outputs,
                threshold=threshold,
                target_sizes=target_sizes,
            )[0]
        detections = []
        labels = results.get("labels", results.get("text_labels", []))
        for score, label, box in zip(
            results["scores"], labels, results["boxes"], strict=False
        ):
            key = owl_label_to_key(label, prompt_labels)
            if key in KEYS:
                x1, y1, x2, y2 = [int(round(v)) for v in box.detach().cpu().tolist()]
                detections.append((key, float(score.detach().cpu()), (x1, y1, x2, y2)))
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
AGENT_RUNTIME = AgentRuntimeState()
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


@app.post("/llm/check")
def llm_check(config: LLMCheckConfig | None = None) -> dict[str, Any]:
    if config is None:
        config = LLMCheckConfig()
    return check_llm(config)


@app.post("/agent/step")
def agent_step(request: AgentStepRequest) -> dict[str, Any]:
    return run_agent_step(request)


@app.post("/agent/act")
def agent_act(request: AgentActRequest) -> dict[str, Any]:
    return run_agent_act(request)


@app.get("/agent/status")
def agent_status() -> dict[str, Any]:
    return build_agent_status()


@app.get("/daemon/status")
def daemon_status() -> dict[str, Any]:
    return build_agent_status()


@app.get("/fusion/status")
def fusion_status() -> dict[str, Any]:
    return {
        "ok": True,
        "scope": "generic screen-prompt fusion boundary",
        "labels": list(KEYS),
        "device": MODEL_HUB.device,
        "default_sensors": normalize_sensor_list(None),
        "available_sensors": list(FUSION_SENSORS),
        "baseline_sensors": list(BASELINE_FUSION_SENSORS),
        "candidate_sensors": list(CANDIDATE_FUSION_SENSORS),
        "sensor_roles": SENSOR_ROLES,
        "evidence_endpoints": {
            "/predict": "ASDW prompt classifier/fusion endpoint",
            "/grounding/review": "generic external GUI bbox evidence review endpoint",
        },
        "loaded_sensors": sorted(MODEL_HUB.loaded),
        "weights": fusion_weights(),
        "models": {
            "classifier": os.getenv(
                "ASDW_CLASSIFIER_MODEL",
                "/mnt/d/asdw-fusion-typer/models/asdw-mobilenetv3-classifier/best",
            ),
            "clip": os.getenv("ASDW_CLIP_MODEL", "openai/clip-vit-base-patch32"),
            "trocr": os.getenv("ASDW_TROCR_MODEL", "microsoft/trocr-small-printed"),
            "owlvit": os.getenv("ASDW_OWLVIT_MODEL", "google/owlvit-base-patch32"),
        },
        "note": "The runtime is not tied to one game; target-specific behavior belongs in prompts, ROI, sensors, and policy.",
    }


@app.post("/grounding/review")
def grounding_review(request: GroundingReviewRequest) -> dict[str, Any]:
    return review_grounding_request(request)


@app.post("/predict")
def predict(request: PredictRequest) -> dict[str, Any]:
    started = time.perf_counter()
    image = decode_image(request.image_b64)
    sensors = normalize_sensor_list(request.sensors)

    owl_detections = MODEL_HUB.detect_owlvit(image) if "owlvit" in sensors else []
    if request.boxes is not None:
        boxes = normalize_request_boxes(request.boxes, image.size)
        box_source = "external"
    else:
        boxes = find_button_boxes(image)
        box_source = "builtin"
        if not boxes and owl_detections:
            boxes = [box for _, _, box in owl_detections]
            box_source = "owlvit"

    detections: list[Detection] = []
    for box in boxes:
        crop = crop_with_margin(image, box, margin=0.18)
        votes = classify_crop(crop, sensors)
        add_owl_votes(votes, box, owl_detections)
        fused_scores = fused_scores_from_votes(votes)
        key, confidence = decision_from_fused_scores(fused_scores)
        detections.append(
            Detection(
                key=key,
                confidence=confidence,
                box=box,
                votes=votes,
                fused_scores=fused_scores,
            )
        )

    detections.sort(key=lambda item: item.box[0])
    min_confidence = env_float("ASDW_SEQUENCE_MIN_CONFIDENCE", DEFAULT_SEQUENCE_MIN_CONFIDENCE)
    sequence = [item.key for item in detections if item.confidence >= min_confidence]
    response: dict[str, Any] = {
        "sequence": sequence,
        "sequence_text": "".join(sequence),
        "detections": [
            {
                "key": item.key,
                "confidence": round(item.confidence, 4),
                "box": item.box,
                "votes": item.votes,
                "fused_scores": round_scores(item.fused_scores),
                "sensor_keys": sensor_best_keys(item.votes),
            }
            for item in detections
        ],
        "fusion": fusion_review_summary(detections, sensors, min_confidence),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "sensors": sensors,
        "device": MODEL_HUB.device,
        "box_source": box_source,
    }
    if request.debug:
        response["debug"] = {
            "image_size": image.size,
            "candidate_count": len(boxes),
            "box_source": box_source,
            "owlvit": [
                {"key": key, "confidence": score, "box": box}
                for key, score, box in owl_detections
            ],
        }
    return response


def check_llm(config: LLMConfig) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        response = requests.get(openai_url(config.base_url, "models"), timeout=config.timeout_sec)
        rtt_ms = round((time.perf_counter() - started) * 1000, 3)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {
            "ok": False,
            "base_url": config.base_url,
            "model": config.model,
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": str(exc),
        }

    available_models = [
        str(item.get("id"))
        for item in payload.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    return {
        "ok": True,
        "base_url": config.base_url,
        "model": config.model,
        "model_available": not available_models or config.model in available_models,
        "available_models": available_models,
        "rtt_ms": rtt_ms,
    }


def run_agent_step(request: AgentStepRequest) -> dict[str, Any]:
    started = time.perf_counter()
    frame: dict[str, Any] | None = None
    prediction: dict[str, Any] | None = None

    try:
        frame = fetch_daemon_frame(
            request.daemon_url,
            request.monitor,
            request.roi,
            request.capture_provider,
            request.target_id,
        )
        prediction = predict(
            PredictRequest(
                image_b64=str(frame["image_b64"]),
                sensors=request.sensors,
                debug=request.debug,
            )
        )
    except Exception as exc:
        decision = blocked_decision(f"Capture or vision prediction failed: {exc}", state="error")
        result = {
            "ok": False,
            "mode": request.mode,
            "timestamp": time.time(),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "frame": frame_metadata(frame),
            "prediction": prediction_summary(prediction),
            "decision": decision.model_dump(),
            "executable": False,
            "error": str(exc),
        }
        AGENT_RUNTIME.record_step(request.mode, result)
        return result

    llm_result = call_llm_controller(request, frame, prediction)
    llm_error: str | None = None
    if llm_result.get("ok"):
        decision = llm_result["decision"]
    else:
        llm_error = str(llm_result.get("error", "LLM controller failed"))
        decision = blocked_decision(llm_error)

    decision, gate_reason = gate_agent_decision(decision, prediction, request.min_action_confidence)
    blocked_reason = gate_reason or llm_error
    result = {
        "ok": bool(llm_result.get("ok")) and gate_reason is None,
        "mode": request.mode,
        "timestamp": time.time(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "frame": frame_metadata(frame),
        "prediction": prediction_summary(prediction),
        "llm": {
            "ok": bool(llm_result.get("ok")),
            "base_url": request.llm.base_url,
            "model": request.llm.model,
            "rtt_ms": llm_result.get("rtt_ms"),
            "error": llm_result.get("error"),
        },
        "decision": decision.model_dump(),
        "blocked_reason": blocked_reason,
        "executable": is_executable_decision(decision),
    }
    AGENT_RUNTIME.record_step(request.mode, result)
    return result


def run_agent_act(request: AgentActRequest) -> dict[str, Any]:
    started = time.perf_counter()
    step: dict[str, Any] | None = None
    decision = request.decision

    if decision is None:
        step_request = AgentStepRequest(
            **request.model_dump(
                exclude={
                    "allow_live_input",
                    "decision",
                    "input_provider",
                    "keep_daemon_queue",
                    "daemon_wait",
                    "daemon_timeout_sec",
                }
            )
        )
        step = run_agent_step(step_request)
        decision = AgentActionDecision.model_validate(step["decision"])
        if not step.get("ok", False):
            result = {
                "ok": False,
                "mode": request.mode,
                "timestamp": time.time(),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "step": step,
                "decision": decision.model_dump(),
                "action_result": {"ok": False, "status": "blocked", "reason": step.get("blocked_reason") or step.get("error")},
            }
            AGENT_RUNTIME.record_act(request.mode, result)
            return result

    decision, gate_reason = gate_agent_decision(decision, None, request.min_action_confidence)
    if gate_reason is not None:
        action_result = {"ok": False, "status": "blocked", "reason": gate_reason}
    else:
        action_result = execute_agent_decision(decision, request)

    result = {
        "ok": bool(action_result.get("ok", False)),
        "mode": request.mode,
        "timestamp": time.time(),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "step": step,
        "decision": decision.model_dump(),
        "action_result": action_result,
    }
    AGENT_RUNTIME.record_act(request.mode, result)
    return result


def fetch_daemon_frame(
    daemon_url: str,
    monitor: int,
    roi: str | None,
    capture_provider: str,
    target_id: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"monitor": monitor, "provider": capture_provider}
    if roi:
        params["roi"] = roi
    if target_id:
        params["target_id"] = target_id
    response = requests.post(f"{daemon_url.rstrip('/')}/frame_base64", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def call_llm_controller(
    request: AgentStepRequest,
    frame: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    messages = build_agent_messages(request, frame, prediction)
    payload = {
        "model": request.llm.model,
        "messages": messages,
        "temperature": request.llm.temperature,
        "max_tokens": request.llm.max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "asdw_agent_action",
                "schema": AgentActionDecision.model_json_schema(),
            },
        },
    }
    started = time.perf_counter()
    try:
        response = requests.post(
            openai_url(request.llm.base_url, "chat/completions"),
            json=payload,
            timeout=request.llm.timeout_sec,
        )
        rtt_ms = round((time.perf_counter() - started) * 1000, 3)
        response.raise_for_status()
        response_payload = response.json()
        content = extract_chat_content(response_payload)
        decision = parse_agent_decision(content)
    except Exception as exc:
        return {
            "ok": False,
            "rtt_ms": round((time.perf_counter() - started) * 1000, 3),
            "error": str(exc),
        }
    return {
        "ok": True,
        "rtt_ms": rtt_ms,
        "decision": decision,
    }


def build_agent_messages(
    request: AgentStepRequest,
    frame: dict[str, Any],
    prediction: dict[str, Any],
) -> list[dict[str, str]]:
    system = (
        "You are the local ASDW input controller. Choose one action for the Windows input daemon. "
        "Return only JSON that matches the provided schema. Valid press_sequence keys are A, S, D, W. "
        "If the visual evidence is empty or uncertain, choose retry_capture, none, or stop instead of inventing keys."
    )
    user_payload = {
        "task": "Decide the next input action for the ASDW prompt automation.",
        "safety_mode": request.mode,
        "min_action_confidence": request.min_action_confidence,
        "frame": frame_metadata(frame),
        "prediction": prediction_summary(prediction),
        "context": request.context,
        "allowed_states": ["idle", "captcha_prompt", "typing_prompt", "blocked", "unknown", "error"],
        "allowed_actions": ["none", "press_sequence", "type_text", "retry_capture", "stop"],
    }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def parse_agent_decision(content: Any) -> AgentActionDecision:
    if isinstance(content, dict):
        return AgentActionDecision.model_validate(content)
    if not isinstance(content, str):
        raise ValueError("LLM response content is not a JSON string")
    return AgentActionDecision.model_validate_json(content)


def extract_chat_content(payload: dict[str, Any]) -> Any:
    choices = payload.get("choices")
    if not choices:
        raise ValueError("LLM response did not include choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict) or "content" not in message:
        raise ValueError("LLM response did not include message.content")
    return message["content"]


def gate_agent_decision(
    decision: AgentActionDecision,
    prediction: dict[str, Any] | None,
    min_confidence: float,
) -> tuple[AgentActionDecision, str | None]:
    if decision.state in {"blocked", "error"} and decision.action in ACTIONABLE_AGENT_ACTIONS:
        reason = f"Action {decision.action} is not allowed while state is {decision.state}."
        return blocked_decision(reason), reason
    if decision.action in ACTIONABLE_AGENT_ACTIONS and decision.confidence < min_confidence:
        reason = f"LLM confidence {decision.confidence:.2f} is below required {min_confidence:.2f}."
        return blocked_decision(reason), reason
    if prediction is not None and decision.action == "press_sequence" and not prediction.get("detections"):
        reason = "Vision prediction returned no detections; press_sequence is blocked."
        return blocked_decision(reason), reason
    return decision, None


def execute_agent_decision(decision: AgentActionDecision, request: AgentActRequest) -> dict[str, Any]:
    if not is_executable_decision(decision):
        return {"ok": True, "status": "skipped", "reason": f"action {decision.action} does not require input"}
    if request.mode == "observe":
        return {"ok": True, "status": "skipped", "reason": "observe mode never sends input"}
    if request.mode == "live" and not request.allow_live_input:
        return {"ok": False, "status": "blocked", "reason": "live mode requires allow_live_input=true"}
    target_guard = check_target_guard(request)
    if target_guard is not None:
        return target_guard

    dry_run = request.mode != "live"
    queue = {
        "keep_queue": request.keep_daemon_queue,
        "wait": request.daemon_wait,
        "timeout_sec": request.daemon_timeout_sec,
    }
    if decision.action == "press_sequence":
        endpoint = "/keys/press"
        body: dict[str, Any] = {
            "keys": decision.keys,
            "dry_run": dry_run,
            "provider": request.input_provider,
            "queue": queue,
        }
    else:
        endpoint = "/text/type_keys"
        body = {"text": decision.text, "dry_run": dry_run, "queue": queue}

    try:
        response = requests.post(
            f"{request.daemon_url.rstrip('/')}{endpoint}",
            json=body,
            timeout=max(15.0, request.daemon_timeout_sec + 5.0),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"ok": False, "status": "failed", "dry_run": dry_run, "error": str(exc)}
    return {"ok": bool(payload.get("ok", False)), "status": payload.get("status", "completed"), "dry_run": dry_run, "daemon": payload}


def check_target_guard(request: AgentActRequest) -> dict[str, Any] | None:
    if not request.target_id:
        return None
    try:
        response = requests.post(
            f"{request.daemon_url.rstrip('/')}/targets/refresh",
            json={"target_id": request.target_id},
            timeout=2,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return {"ok": False, "status": "blocked", "reason": f"target guard failed: {exc}"}
    target = payload.get("target") if isinstance(payload, dict) else None
    if not target or target.get("is_stale"):
        return {"ok": False, "status": "blocked", "reason": "target is stale", "target": target}
    return None


def build_agent_status() -> dict[str, Any]:
    heartbeat_config = HeartbeatConfig(timeout_sec=env_float("ASDW_DAEMON_STATUS_TIMEOUT_SEC", 1.0))
    llm_config = LLMConfig(timeout_sec=env_float("ASDW_LLM_STATUS_TIMEOUT_SEC", 1.0))
    return {
        "ok": True,
        "timestamp": time.time(),
        "vision": {
            "ok": cv2 is not None,
            "device": MODEL_HUB.device,
            "sensors_loaded": sorted(MODEL_HUB.loaded),
            "cv2": cv2 is not None,
        },
        "daemon": HEARTBEAT.ping_once(heartbeat_config),
        "llm": check_llm(llm_config),
        "agent": AGENT_RUNTIME.status(),
    }


def prediction_summary(prediction: dict[str, Any] | None) -> dict[str, Any] | None:
    if prediction is None:
        return None
    return {
        "sequence": prediction.get("sequence"),
        "sequence_text": prediction.get("sequence_text"),
        "detections": prediction.get("detections", []),
        "latency_ms": prediction.get("latency_ms"),
        "sensors": prediction.get("sensors"),
        "device": prediction.get("device"),
    }


def frame_metadata(frame: dict[str, Any] | None) -> dict[str, Any] | None:
    if frame is None:
        return None
    return {
        "width": frame.get("width"),
        "height": frame.get("height"),
        "roi": frame.get("roi"),
        "full_monitor": frame.get("full_monitor"),
        "provider": frame.get("provider"),
        "target": frame.get("target"),
        "region": frame.get("region"),
    }


def blocked_decision(reason: str, state: Literal["blocked", "error"] = "blocked") -> AgentActionDecision:
    return AgentActionDecision(
        state=state,
        action="none",
        keys=[],
        text=None,
        confidence=0.0,
        reason=reason[:500] or "blocked",
    )


def is_executable_decision(decision: AgentActionDecision) -> bool:
    return decision.action in ACTIONABLE_AGENT_ACTIONS and decision.state not in {"blocked", "error"}


def openai_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def normalize_sensor_list(sensors: list[str] | None) -> list[str]:
    if not sensors:
        raw = os.getenv("ASDW_SENSORS", "template,classifier")
        sensors = [item.strip() for item in raw.split(",") if item.strip()]
    allowed = set(FUSION_SENSORS)
    selected = [sensor.lower() for sensor in sensors if sensor.lower() in allowed]
    return selected or ["template"]


def decode_image(image_b64: str) -> Image.Image:
    if "," in image_b64 and image_b64.lstrip().startswith("data:"):
        image_b64 = image_b64.split(",", 1)[1]
    data = base64.b64decode(image_b64)
    return Image.open(io.BytesIO(data)).convert("RGB")


def normalize_request_boxes(
    boxes: list[tuple[int, int, int, int]],
    image_size: tuple[int, int],
) -> list[tuple[int, int, int, int]]:
    width, height = image_size
    normalized: list[tuple[int, int, int, int]] = []
    for box in boxes:
        x1, y1, x2, y2 = [int(round(value)) for value in box]
        x1 = max(0, min(width, x1))
        x2 = max(0, min(width, x2))
        y1 = max(0, min(height, y1))
        y2 = max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1:
            continue
        normalized.append((x1, y1, x2, y2))
    return sorted(normalized, key=lambda item: (item[0], item[1]))


def review_grounding_request(request: GroundingReviewRequest) -> dict[str, Any]:
    started = time.perf_counter()
    image = decode_image(request.image_b64)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for index, element in enumerate(request.elements):
        boxes = normalize_request_boxes([element.box], image.size)
        if not boxes:
            rejected.append(
                {
                    "index": index,
                    "id": element.id,
                    "box": list(element.box),
                    "reason": "box is outside image bounds or has no area",
                }
            )
            continue
        box = boxes[0]
        accepted.append(grounding_element_evidence(index, element, box, image, request.instruction))

    return {
        "ok": True,
        "scope": "generic GUI grounding evidence review",
        "source": request.source,
        "instruction": request.instruction,
        "image_size": {"width": image.size[0], "height": image.size[1]},
        "element_count": len(request.elements),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "elements": accepted,
        "rejected_elements": rejected,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "note": "This endpoint reviews external GUI element boxes; it does not classify ASDW keys or send input.",
    }


def grounding_element_evidence(
    index: int,
    element: GroundingElementInput,
    box: tuple[int, int, int, int],
    image: Image.Image,
    instruction: str | None,
) -> dict[str, Any]:
    x1, y1, x2, y2 = box
    width, height = image.size
    box_width = x2 - x1
    box_height = y2 - y1
    element_text = " ".join(
        item for item in [element.label, element.text, element.category] if item
    )
    return {
        "index": index,
        "id": element.id,
        "label": element.label,
        "text": element.text,
        "category": element.category,
        "source": element.source,
        "confidence": element.confidence,
        "box": list(box),
        "box_norm_xyxy": [
            round(x1 / width, 6),
            round(y1 / height, 6),
            round(x2 / width, 6),
            round(y2 / height, 6),
        ],
        "center_xy": [round((x1 + x2) / 2), round((y1 + y2) / 2)],
        "size": {"width": box_width, "height": box_height},
        "area_ratio": round((box_width * box_height) / max(width * height, 1), 8),
        "instruction_overlap": text_overlap(instruction, element_text),
        "crop": crop_summary(image, box),
        "metadata": element.metadata,
    }


def crop_summary(image: Image.Image, box: tuple[int, int, int, int]) -> dict[str, Any]:
    crop = image.crop(box).convert("RGB")
    arr = np.asarray(crop, dtype=np.float32)
    if arr.size == 0:
        return {"width": 0, "height": 0, "mean_rgb": [0.0, 0.0, 0.0], "brightness": 0.0}
    mean_rgb = arr.reshape(-1, 3).mean(axis=0)
    return {
        "width": crop.size[0],
        "height": crop.size[1],
        "mean_rgb": [round(float(value), 3) for value in mean_rgb],
        "brightness": round(float(mean_rgb.mean() / 255.0), 6),
    }


def text_overlap(left: str | None, right: str | None) -> dict[str, Any]:
    left_tokens = tokenize_text(left)
    right_tokens = tokenize_text(right)
    if not left_tokens or not right_tokens:
        return {"score": 0.0, "tokens": []}
    shared = sorted(left_tokens & right_tokens)
    score = len(shared) / max(len(left_tokens), 1)
    return {"score": round(score, 4), "tokens": shared}


def tokenize_text(value: str | None) -> set[str]:
    if not value:
        return set()
    return {token for token in re.findall(r"[a-z0-9_]+", value.lower()) if len(token) > 1}


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


def owl_label_to_key(label: Any, prompt_labels: list[str]) -> str:
    if hasattr(label, "detach"):
        label_index = int(label.detach().cpu())
        return KEYS[label_index] if 0 <= label_index < len(KEYS) else "?"
    if isinstance(label, (int, np.integer)):
        return KEYS[int(label)] if 0 <= int(label) < len(KEYS) else "?"
    text = str(label).upper()
    for key, prompt in zip(KEYS, prompt_labels, strict=True):
        if text == prompt.upper() or text.endswith(f" {key}") or text == key:
            return key
    for key in KEYS:
        if key in text.split():
            return key
    return "?"


def fuse_votes(votes: dict[str, dict[str, float]]) -> tuple[str, float]:
    return decision_from_fused_scores(fused_scores_from_votes(votes))


def fused_scores_from_votes(votes: dict[str, dict[str, float]]) -> dict[str, float]:
    weights = fusion_weights()
    fused = {key: 0.0 for key in KEYS}
    total_weight = 0.0
    for sensor, scores in votes.items():
        weight = weights.get(sensor, 1.0)
        if weight <= 0:
            continue
        total_weight += weight
        for key in KEYS:
            fused[key] += weight * float(scores.get(key, 0.0))
    if total_weight <= 0:
        return {key: 0.0 for key in KEYS}
    return {key: value / total_weight for key, value in fused.items()}


def decision_from_fused_scores(fused_scores: dict[str, float]) -> tuple[str, float]:
    if not fused_scores or max(fused_scores.values(), default=0.0) <= 0:
        return "?", 0.0
    best_key = max(fused_scores, key=fused_scores.get)
    sorted_scores = sorted(fused_scores.values(), reverse=True)
    margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
    confidence = max(0.0, min(1.0, sorted_scores[0] * 0.75 + margin * 0.50))
    return best_key, float(confidence)


def fusion_review_summary(
    detections: list[Detection],
    sensors: list[str],
    min_confidence: float,
) -> dict[str, Any]:
    sensor_sequences: dict[str, str] = {}
    for sensor in sensors:
        sensor_sequences[sensor] = "".join(
            sensor_best_keys(item.votes).get(sensor, "?") for item in detections
        )

    disagreements = []
    agreement_positions = 0
    for index, item in enumerate(detections):
        sensor_keys = sensor_best_keys(item.votes)
        concrete_keys = [key for key in sensor_keys.values() if key in KEYS]
        agrees = bool(concrete_keys) and all(key == item.key for key in concrete_keys)
        if agrees:
            agreement_positions += 1
        if not agrees or item.confidence < min_confidence:
            disagreements.append(
                {
                    "index": index,
                    "box": item.box,
                    "fused_key": item.key,
                    "confidence": round(item.confidence, 4),
                    "sensor_keys": sensor_keys,
                }
            )

    return {
        "sequence_min_confidence": round(min_confidence, 4),
        "accepted_count": sum(1 for item in detections if item.confidence >= min_confidence),
        "rejected_count": sum(1 for item in detections if item.confidence < min_confidence),
        "sensor_sequences": sensor_sequences,
        "agreement_rate": round(agreement_positions / len(detections), 4) if detections else 0.0,
        "disagreements": disagreements,
    }


def sensor_best_keys(votes: dict[str, dict[str, float]]) -> dict[str, str]:
    best: dict[str, str] = {}
    for sensor, scores in votes.items():
        best[sensor] = max(scores, key=scores.get) if scores else "?"
    return best


def round_scores(scores: dict[str, float]) -> dict[str, float]:
    return {key: round(float(scores.get(key, 0.0)), 6) for key in KEYS}


def fusion_weights() -> dict[str, float]:
    return {
        "template": float(os.getenv("ASDW_WEIGHT_TEMPLATE", "0.35")),
        "classifier": float(os.getenv("ASDW_WEIGHT_CLASSIFIER", "1.25")),
        "clip": float(os.getenv("ASDW_WEIGHT_CLIP", "1.00")),
        "trocr": float(os.getenv("ASDW_WEIGHT_TROCR", "1.10")),
        "owlvit": float(os.getenv("ASDW_WEIGHT_OWLVIT", "0.50")),
    }


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
