from __future__ import annotations

import base64
import ctypes
import importlib
import importlib.util
import io
import json
import random
import threading
import time
import uuid
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Annotated, Any

import mss
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field


DEFAULT_MODEL_URL = "http://127.0.0.1:7868/predict"
VALID_KEYS = {"A", "S", "D", "W"}
INPUT_PROVIDERS = {"builtin", "pydirectinput"}
CAPTURE_PROVIDERS = {"mss", "dxcam", "windows_capture"}
WINDOW_PROVIDERS = {"auto", "builtin", "pywinctl"}
SW_RESTORE = 9
WM_IME_CONTROL = 0x0283
IMC_GETOPENSTATUS = 0x0005
IMC_SETOPENSTATUS = 0x0006
IMC_GETCONVERSIONMODE = 0x0001
LANG_KOREAN = 0x0412
HANGUL_BASE = 0xAC00
HANGUL_END = 0xD7A3
HANGUL_JUNG_COUNT = 21
HANGUL_JONG_COUNT = 28

CHOSEONG_KEYS = {
    0: "r",
    1: "R",
    2: "s",
    3: "e",
    4: "E",
    5: "f",
    6: "a",
    7: "q",
    8: "Q",
    9: "t",
    10: "T",
    11: "d",
    12: "w",
    13: "W",
    14: "c",
    15: "z",
    16: "x",
    17: "v",
    18: "g",
}
JUNGSEONG_KEYS = {
    0: "k",
    1: "o",
    2: "i",
    3: "O",
    4: "j",
    5: "p",
    6: "u",
    7: "P",
    8: "h",
    9: "hk",
    10: "ho",
    11: "hl",
    12: "y",
    13: "n",
    14: "nj",
    15: "np",
    16: "nl",
    17: "b",
    18: "m",
    19: "ml",
    20: "l",
}
JONGSEONG_KEYS = {
    0: "",
    1: "r",
    2: "R",
    3: "rt",
    4: "s",
    5: "sw",
    6: "sg",
    7: "e",
    8: "f",
    9: "fr",
    10: "fa",
    11: "fq",
    12: "ft",
    13: "fx",
    14: "fv",
    15: "fg",
    16: "a",
    17: "q",
    18: "qt",
    19: "t",
    20: "T",
    21: "d",
    22: "w",
    23: "c",
    24: "z",
    25: "x",
    26: "v",
    27: "g",
}
COMPAT_JAMO_KEYS = {
    "ㄱ": "r",
    "ㄲ": "R",
    "ㄴ": "s",
    "ㄷ": "e",
    "ㄸ": "E",
    "ㄹ": "f",
    "ㅁ": "a",
    "ㅂ": "q",
    "ㅃ": "Q",
    "ㅅ": "t",
    "ㅆ": "T",
    "ㅇ": "d",
    "ㅈ": "w",
    "ㅉ": "W",
    "ㅊ": "c",
    "ㅋ": "z",
    "ㅌ": "x",
    "ㅍ": "v",
    "ㅎ": "g",
    "ㅏ": "k",
    "ㅐ": "o",
    "ㅑ": "i",
    "ㅒ": "O",
    "ㅓ": "j",
    "ㅔ": "p",
    "ㅕ": "u",
    "ㅖ": "P",
    "ㅗ": "h",
    "ㅘ": "hk",
    "ㅙ": "ho",
    "ㅚ": "hl",
    "ㅛ": "y",
    "ㅜ": "n",
    "ㅝ": "nj",
    "ㅞ": "np",
    "ㅟ": "nl",
    "ㅠ": "b",
    "ㅡ": "m",
    "ㅢ": "ml",
    "ㅣ": "l",
}
SHIFTED_ASCII_KEYS = {
    "!": "shift+1",
    "@": "shift+2",
    "#": "shift+3",
    "$": "shift+4",
    "%": "shift+5",
    "^": "shift+6",
    "&": "shift+7",
    "*": "shift+8",
    "(": "shift+9",
    ")": "shift+0",
    "_": "shift+-",
    "+": "shift+=",
    "{": "shift+[",
    "}": "shift+]",
    "|": "shift+\\",
    ":": "shift+;",
    '"': "shift+'",
    "<": "shift+,",
    ">": "shift+.",
    "?": "shift+/",
    "~": "shift+`",
}
SPECIAL_TEXT_KEYS = {
    "♥": "alt+num3",
}

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12
VK_SHIFT = 0x10
VK_SPACE = 0x20
VK_NUMPAD0 = 0x60
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
VK_CODES = {
    "space": VK_SPACE,
    "shift": VK_SHIFT,
    "alt": VK_MENU,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
}
for digit in range(10):
    VK_CODES[str(digit)] = 0x30 + digit
    VK_CODES[f"num{digit}"] = VK_NUMPAD0 + digit
for letter_index, letter in enumerate("abcdefghijklmnopqrstuvwxyz"):
    VK_CODES[letter] = 0x41 + letter_index


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint),
        ("union", INPUT_UNION),
    ]


class InputAdapter:
    name = "abstract"

    def press(self, key: str, hold: float) -> None:
        raise NotImplementedError


class SendInputKeyboardAdapter(InputAdapter):
    name = "sendinput"

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def press(self, key: str, hold: float) -> None:
        modifiers, key_name = split_key_chord(key)
        for modifier in modifiers:
            self._key_down(modifier)
        try:
            self._key_down(key_name)
            time.sleep(hold)
            self._key_up(key_name)
        finally:
            for modifier in reversed(modifiers):
                self._key_up(modifier)

    def _key_down(self, key: str) -> None:
        self._send(key, key_up=False)

    def _key_up(self, key: str) -> None:
        self._send(key, key_up=True)

    def _send(self, key: str, key_up: bool) -> None:
        vk = key_to_vk(key)
        flags = KEYEVENTF_KEYUP if key_up else 0
        item = INPUT(
            type=INPUT_KEYBOARD,
            union=INPUT_UNION(
                ki=KEYBDINPUT(
                    wVk=vk,
                    wScan=0,
                    dwFlags=flags,
                    time=0,
                    dwExtraInfo=0,
                )
            ),
        )
        sent = self.user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item))
        if sent != 1:
            raise ctypes.WinError(ctypes.get_last_error())


class DryRunInputAdapter(InputAdapter):
    name = "dry-run"

    def press(self, key: str, hold: float) -> None:
        time.sleep(hold)


class PyDirectInputAdapter(InputAdapter):
    name = "pydirectinput"

    def __init__(self) -> None:
        self.module = load_pydirectinput()

    def press(self, key: str, hold: float) -> None:
        modifiers, key_name = split_key_chord(key)
        key_name = key_name.lower() if len(key_name) == 1 else key_name
        if hasattr(self.module, "keyDown") and hasattr(self.module, "keyUp"):
            for modifier in modifiers:
                self.module.keyDown(normalize_pydirectinput_key(modifier))
            try:
                self.module.keyDown(normalize_pydirectinput_key(key_name))
                time.sleep(hold)
                self.module.keyUp(normalize_pydirectinput_key(key_name))
            finally:
                for modifier in reversed(modifiers):
                    self.module.keyUp(normalize_pydirectinput_key(modifier))
            return
        if modifiers:
            raise RuntimeError("pydirectinput provider does not expose keyDown/keyUp for key chords")
        if not hasattr(self.module, "press"):
            raise RuntimeError("pydirectinput provider does not expose press/keyDown/keyUp")
        self.module.press(normalize_pydirectinput_key(key_name))
        time.sleep(hold)


@dataclass(frozen=True)
class Roi:
    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_string(cls, value: str | None) -> "Roi":
        if not value:
            raise ValueError("roi is empty")
        parts = [float(item) for item in value.replace(",", " ").split()]
        if len(parts) != 4:
            raise ValueError("roi must contain four numbers: left top right bottom")
        left, top, right, bottom = parts
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("roi values must be normalized fractions")
        return cls(left, top, right, bottom)


class PredictOnceRequest(BaseModel):
    model_url: str = Field(default=DEFAULT_MODEL_URL)
    monitor: int = Field(default=1, ge=0)
    roi: str | None = Field(
        default=None,
        description="Optional normalized 'left top right bottom'. Omit to send the full monitor.",
    )
    capture_provider: str = Field(default="mss", description="mss, dxcam, or windows_capture.")
    target_id: str | None = Field(default=None, description="Optional selected window target id, e.g. hwnd:1234.")
    sensors: list[str] = Field(default_factory=lambda: ["template", "classifier"])
    debug: bool = False


class HumanTiming(BaseModel):
    initial_delay_ms: tuple[int, int] = Field(default=(80, 220))
    hold_ms: tuple[int, int] = Field(default=(28, 55))
    between_ms: tuple[int, int] = Field(default=(45, 85))
    long_pause_chance: float = Field(default=0.04, ge=0.0, le=1.0)
    long_pause_ms: tuple[int, int] = Field(default=(140, 280))


class QueueOptions(BaseModel):
    keep_queue: bool = False
    wait: bool = True
    timeout_sec: float = Field(default=30.0, ge=0.1, le=300.0)


class PressKeysRequest(BaseModel):
    keys: list[str] | str
    dry_run: bool = False
    provider: str = Field(default="builtin", description="builtin or pydirectinput.")
    timing: HumanTiming = Field(default_factory=HumanTiming)
    queue: QueueOptions = Field(default_factory=QueueOptions)


class TypeTextKeysRequest(BaseModel):
    text: str
    dry_run: bool = False
    require_korean_ime: bool = True
    timing: HumanTiming = Field(default_factory=HumanTiming)
    queue: QueueOptions = Field(default_factory=QueueOptions)


class PredictAndPressRequest(PredictOnceRequest):
    dry_run: bool = False
    min_confidence: float = Field(default=0.30, ge=0.0, le=1.0)
    input_provider: str = Field(default="builtin", description="builtin or pydirectinput.")
    timing: HumanTiming = Field(default_factory=HumanTiming)
    queue: QueueOptions = Field(default_factory=QueueOptions)


class TargetSelectRequest(BaseModel):
    target_id: str | None = None
    window_id: int | None = None
    title_contains: str | None = None
    provider: str = "auto"
    activate: bool = False


@dataclass
class InputJob:
    job_id: str
    kind: str
    created_at: float
    func: Any
    cancel_event: threading.Event
    status: str = "queued"
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    done_event: threading.Event = dataclass_field(default_factory=threading.Event)


class InputJobQueue:
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jobs: deque[InputJob] = deque()
        self._active: InputJob | None = None
        self._last_completed: InputJob | None = None
        self._worker = threading.Thread(target=self._run, name="asdw-input-worker", daemon=True)
        self._worker.start()

    def submit(
        self,
        kind: str,
        func: Any,
        options: QueueOptions,
    ) -> dict[str, Any]:
        job = InputJob(
            job_id=str(uuid.uuid4()),
            kind=kind,
            created_at=time.time(),
            func=func,
            cancel_event=threading.Event(),
        )
        discarded: list[str] = []
        with self._condition:
            if not options.keep_queue:
                discarded = self._discard_locked()
            self._jobs.append(job)
            self._condition.notify()

        if not options.wait:
            return {
                "ok": True,
                "queued": True,
                "job_id": job.job_id,
                "kind": job.kind,
                "discarded_jobs": discarded,
                "queue": self.status(),
            }

        completed = job.done_event.wait(options.timeout_sec)
        if not completed:
            return {
                "ok": True,
                "queued": True,
                "job_id": job.job_id,
                "kind": job.kind,
                "status": job.status,
                "discarded_jobs": discarded,
                "queue": self.status(),
            }
        result = job.result or {"ok": job.error is None}
        result["job"] = self._job_summary(job)
        result["discarded_jobs"] = discarded
        return result

    def status(self) -> dict[str, Any]:
        with self._condition:
            return {
                "active": self._job_summary(self._active) if self._active else None,
                "queued": [self._job_summary(job) for job in self._jobs],
                "queued_count": len(self._jobs),
                "last_completed": self._job_summary(self._last_completed) if self._last_completed else None,
            }

    def _discard_locked(self) -> list[str]:
        discarded: list[str] = []
        while self._jobs:
            job = self._jobs.popleft()
            job.cancel_event.set()
            job.status = "discarded"
            job.finished_at = time.time()
            job.result = {"ok": False, "status": "discarded", "job_id": job.job_id}
            job.done_event.set()
            discarded.append(job.job_id)
        if self._active is not None:
            self._active.cancel_event.set()
            discarded.append(self._active.job_id)
        return discarded

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._jobs:
                    self._condition.wait()
                job = self._jobs.popleft()
                self._active = job
                job.status = "running"
                job.started_at = time.time()
            try:
                if job.cancel_event.is_set():
                    result = {"ok": False, "status": "cancelled", "job_id": job.job_id}
                else:
                    result = job.func(job.cancel_event)
                if job.cancel_event.is_set() and result.get("ok", True):
                    result = {**result, "ok": False, "status": "cancelled"}
                job.result = result
                job.status = str(result.get("status", "completed" if result.get("ok", False) else "failed"))
            except Exception as exc:
                job.error = str(exc)
                job.status = "failed"
                job.result = {"ok": False, "status": "failed", "error": str(exc), "job_id": job.job_id}
            finally:
                job.finished_at = time.time()
                job.done_event.set()
                with self._condition:
                    self._last_completed = job
                    if self._active is job:
                        self._active = None
                    self._condition.notify_all()

    @staticmethod
    def _job_summary(job: InputJob | None) -> dict[str, Any] | None:
        if job is None:
            return None
        return {
            "job_id": job.job_id,
            "kind": job.kind,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "cancel_requested": job.cancel_event.is_set(),
        }


class CaptureDaemon:
    def __init__(self) -> None:
        self.started_at = time.time()

    def list_monitors(self) -> list[dict[str, int]]:
        with mss.mss() as screen:
            return [dict(monitor) for monitor in screen.monitors]

    def capture(
        self,
        monitor_index: int,
        roi: Roi | None = None,
        provider: str = "mss",
        target_id: str | None = None,
    ) -> Image.Image:
        image, _ = self.capture_with_metadata(monitor_index, roi, provider, target_id)
        return image

    def capture_with_metadata(
        self,
        monitor_index: int,
        roi: Roi | None = None,
        provider: str = "mss",
        target_id: str | None = None,
    ) -> tuple[Image.Image, dict[str, Any]]:
        provider_name = normalize_capture_provider(provider)
        if target_id:
            target = get_target_by_id(target_id)
            if target.get("is_stale"):
                raise RuntimeError(f"target {target_id} is stale or unavailable")
            bounds = target.get("bounds") or {}
            region = {
                "left": int(bounds["left"]),
                "top": int(bounds["top"]),
                "width": int(bounds["width"]),
                "height": int(bounds["height"]),
            }
            region = monitor_to_region(region, roi)
            image = self._capture_region(provider_name, monitor_index, region)
            return image, capture_metadata(provider_name, monitor_index, roi, region, target)

        with mss.mss() as screen:
            if monitor_index >= len(screen.monitors):
                raise ValueError(f"monitor {monitor_index} is not available")
            monitor = screen.monitors[monitor_index]
            region = monitor_to_region(monitor, roi)
        image = self._capture_region(provider_name, monitor_index, region)
        return image, capture_metadata(provider_name, monitor_index, roi, region, None)

    def _capture_region(self, provider: str, monitor_index: int, region: dict[str, int]) -> Image.Image:
        if provider == "mss":
            with mss.mss() as screen:
                shot = screen.grab(region)
                return Image.frombytes("RGB", shot.size, shot.rgb)
        if provider == "dxcam":
            return capture_region_dxcam(monitor_index, region)
        raise RuntimeError("windows_capture is registered as experimental but is not wired as a default daemon provider")


daemon = CaptureDaemon()
KEYBOARD_ADAPTER = SendInputKeyboardAdapter()
PYDIRECTINPUT_ADAPTER: PyDirectInputAdapter | None = None
selected_target_lock = threading.Lock()
selected_target_id: str | None = None
input_jobs = InputJobQueue()
app = FastAPI(title="ASDW Windows Capture Daemon", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "daemon_time": time.time(),
        "uptime_sec": round(time.time() - daemon.started_at, 3),
        "monitors": daemon.list_monitors(),
        "default_capture": "full_monitor",
        "input_state": get_input_state(),
        "input_queue": input_jobs.status(),
        "capabilities": daemon_capabilities(),
        "providers": provider_capabilities(),
        "selected_target": get_selected_target(),
        "privilege": privilege_status(),
        "input_adapter": KEYBOARD_ADAPTER.name,
    }


@app.get("/ping")
def ping() -> dict[str, Any]:
    return {
        "ok": True,
        "daemon_time": time.time(),
        "uptime_sec": round(time.time() - daemon.started_at, 3),
        "queue": input_jobs.status(),
        "capabilities": daemon_capabilities(),
        "providers": provider_capabilities(),
        "selected_target": get_selected_target(),
        "privilege": privilege_status(),
    }


@app.get("/queue/status")
def queue_status() -> dict[str, Any]:
    return input_jobs.status()


@app.get("/providers")
def providers() -> dict[str, Any]:
    return provider_capabilities()


@app.get("/targets")
def targets(provider: str = "auto") -> dict[str, Any]:
    provider_name, target_list, fallback_error = list_window_targets(provider)
    return {
        "ok": True,
        "provider": provider_name,
        "fallback_error": fallback_error,
        "selected_target_id": get_selected_target_id(),
        "targets": target_list,
    }


@app.post("/targets/select")
def targets_select(request: TargetSelectRequest) -> dict[str, Any]:
    target = select_target(request)
    if request.activate and target and not target.get("is_stale"):
        target["activated"] = activate_target(str(target["target_id"]))
    return {"ok": bool(target), "selected": target}


@app.get("/targets/current")
def targets_current(target_id: str | None = None) -> dict[str, Any]:
    target = get_target_by_id(target_id) if target_id else get_selected_target()
    return {"ok": bool(target), "selected_target_id": get_selected_target_id(), "target": target}


@app.post("/targets/refresh")
def targets_refresh(request: TargetSelectRequest | None = None) -> dict[str, Any]:
    target_id = request.target_id if request and request.target_id else get_selected_target_id()
    target = get_target_by_id(target_id) if target_id else get_selected_target()
    ok = bool(target) and not bool(target.get("is_stale")) if target else False
    return {"ok": ok, "target": target}


@app.get("/frame")
def frame(
    monitor: Annotated[int, Query(ge=0)] = 1,
    roi: str | None = None,
    draw_roi: bool = False,
    provider: str = "mss",
    target_id: str | None = None,
) -> Response:
    parsed_roi = Roi.from_string(roi) if roi else None
    image = daemon.capture(monitor, parsed_roi, provider=provider, target_id=target_id)
    if draw_roi:
        image = image.copy()
        ImageDraw.Draw(image).rectangle((0, 0, image.width - 1, image.height - 1), outline=(255, 232, 0), width=3)
    return Response(content=encode_image(image, "PNG"), media_type="image/png")


@app.get("/stream")
def stream(
    monitor: Annotated[int, Query(ge=0)] = 1,
    roi: str | None = None,
    fps: Annotated[float, Query(gt=0.1, le=30)] = 8,
    jpeg_quality: Annotated[int, Query(ge=20, le=95)] = 70,
    provider: str = "mss",
    target_id: str | None = None,
) -> StreamingResponse:
    parsed_roi = Roi.from_string(roi) if roi else None
    interval = 1.0 / fps

    def generate():
        while True:
            started = time.perf_counter()
            image = daemon.capture(monitor, parsed_roi, provider=provider, target_id=target_id)
            payload = encode_image(image, "JPEG", quality=jpeg_quality)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
                + payload
                + b"\r\n"
            )
            elapsed = time.perf_counter() - started
            if elapsed < interval:
                time.sleep(interval - elapsed)

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/predict_once")
def predict_once(request: PredictOnceRequest) -> dict[str, Any]:
    return run_prediction(request)


@app.post("/keys/press")
def press_keys(request: PressKeysRequest) -> dict[str, Any]:
    keys = normalize_keys(request.keys)
    normalize_input_provider(request.provider)
    return input_jobs.submit(
        "keys.press",
        lambda cancel_event: run_press_keys_job(request, keys, cancel_event),
        request.queue,
    )


@app.post("/text/type_keys")
def type_text_keys(request: TypeTextKeysRequest) -> dict[str, Any]:
    input_state = get_input_state()
    if request.require_korean_ime and contains_hangul(request.text):
        if not input_state.get("is_korean_layout"):
            return {
                "ok": False,
                "dry_run": request.dry_run,
                "text": request.text,
                "keys": text_to_physical_keys(request.text),
                "input_state": input_state,
                "error": "Korean keyboard layout is not active in the focused window.",
            }
    return input_jobs.submit(
        "text.type_keys",
        lambda cancel_event: run_type_text_job(request, input_state, cancel_event),
        request.queue,
    )


def run_press_keys_job(
    request: PressKeysRequest,
    keys: list[str],
    cancel_event: threading.Event,
) -> dict[str, Any]:
    events = press_key_sequence(
        keys,
        dry_run=request.dry_run,
        provider=request.provider,
        timing=request.timing,
        cancel_event=cancel_event,
    )
    return {
        "ok": not cancel_event.is_set(),
        "status": "cancelled" if cancel_event.is_set() else "completed",
        "dry_run": request.dry_run,
        "provider": request.provider,
        "input_adapter": selected_input_adapter_name(request.dry_run, request.provider),
        "keys": keys,
        "events": events,
    }


def run_type_text_job(
    request: TypeTextKeysRequest,
    input_state: dict[str, Any],
    cancel_event: threading.Event,
) -> dict[str, Any]:
    result = type_text_as_physical_keys(
        request.text,
        dry_run=request.dry_run,
        timing=request.timing,
        cancel_event=cancel_event,
    )
    return {
        "ok": not cancel_event.is_set(),
        "status": "cancelled" if cancel_event.is_set() else "completed",
        "dry_run": request.dry_run,
        "input_adapter": "dry-run" if request.dry_run else KEYBOARD_ADAPTER.name,
        "text": request.text,
        "keys": result["keys"],
        "events": result["events"],
        "input_state": input_state,
        "final_input_state": get_input_state(),
        "note": "Korean and ASCII segments are typed with IME on/off switching in the focused window.",
    }


@app.post("/predict_and_press")
def predict_and_press(request: PredictAndPressRequest) -> dict[str, Any]:
    result = run_prediction(request)
    detections = result.get("detections", [])
    keys = [
        str(item["key"]).upper()
        for item in detections
        if float(item.get("confidence", 0.0)) >= request.min_confidence
    ]
    keys = [key for key in keys if key in VALID_KEYS]
    if keys:
        normalize_input_provider(request.input_provider)
        action = input_jobs.submit(
            "predict_and_press.keys",
            lambda cancel_event: run_predict_press_job(request, keys, cancel_event),
            request.queue,
        )
    else:
        action = {"ok": True, "status": "skipped", "reason": "no keys above confidence threshold", "keys": []}
    result["action"] = action
    return result


def run_predict_press_job(
    request: PredictAndPressRequest,
    keys: list[str],
    cancel_event: threading.Event,
) -> dict[str, Any]:
    events = press_key_sequence(
        keys,
        dry_run=request.dry_run,
        provider=request.input_provider,
        timing=request.timing,
        cancel_event=cancel_event,
    )
    return {
        "ok": not cancel_event.is_set(),
        "status": "cancelled" if cancel_event.is_set() else "completed",
        "type": "press_sequence",
        "dry_run": request.dry_run,
        "provider": request.input_provider,
        "input_adapter": selected_input_adapter_name(request.dry_run, request.input_provider),
        "min_confidence": request.min_confidence,
        "keys": keys,
        "events": events,
    }


@app.post("/frame_base64")
def frame_base64(
    monitor: Annotated[int, Query(ge=0)] = 1,
    roi: str | None = None,
    provider: str = "mss",
    target_id: str | None = None,
) -> dict[str, Any]:
    parsed_roi = Roi.from_string(roi) if roi else None
    image, metadata = daemon.capture_with_metadata(monitor, parsed_roi, provider=provider, target_id=target_id)
    png = encode_image(image, "PNG")
    return {
        "image_b64": base64.b64encode(png).decode("ascii"),
        "width": image.width,
        "height": image.height,
        "roi": [parsed_roi.left, parsed_roi.top, parsed_roi.right, parsed_roi.bottom] if parsed_roi else None,
        "full_monitor": metadata["full_monitor"],
        "provider": metadata["provider"],
        "monitor": metadata["monitor"],
        "region": metadata["region"],
        "target": metadata["target"],
    }


def run_prediction(request: PredictOnceRequest) -> dict[str, Any]:
    roi = Roi.from_string(request.roi) if request.roi else None
    image, metadata = daemon.capture_with_metadata(
        request.monitor,
        roi,
        provider=request.capture_provider,
        target_id=request.target_id,
    )
    payload = {
        "image_b64": base64.b64encode(encode_image(image, "PNG")).decode("ascii"),
        "sensors": request.sensors,
        "debug": request.debug,
    }
    started = time.perf_counter()
    response = requests.post(request.model_url, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()
    result["capture_daemon"] = {
        "monitor": request.monitor,
        "roi": [roi.left, roi.top, roi.right, roi.bottom] if roi else None,
        "full_monitor": metadata["full_monitor"],
        "provider": metadata["provider"],
        "target": metadata["target"],
        "region": metadata["region"],
        "model_url": request.model_url,
        "roundtrip_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    return result


def normalize_keys(keys: list[str] | str) -> list[str]:
    if isinstance(keys, str):
        raw = list(keys.replace(" ", "").upper())
    else:
        raw = [str(key).upper() for key in keys]
    normalized = [key for key in raw if key in VALID_KEYS]
    if not normalized:
        raise ValueError("No valid ASDW keys were provided")
    return normalized


def press_key_sequence(
    keys: list[str],
    dry_run: bool,
    provider: str,
    timing: HumanTiming,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    return press_physical_keys([key.lower() for key in keys], dry_run, provider, timing, cancel_event)


def press_physical_keys(
    keys: list[str],
    dry_run: bool,
    provider: str,
    timing: HumanTiming,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    adapter = get_input_adapter(provider, dry_run=dry_run)
    events = []
    initial_delay = random_delay(timing.initial_delay_ms)
    cancelable_sleep(initial_delay, cancel_event)
    events.append({"type": "initial_delay", "sec": round(initial_delay, 4)})

    for index, key in enumerate(keys):
        if cancel_event is not None and cancel_event.is_set():
            events.append({"type": "cancelled", "index": index})
            break
        key_name = key.lower()
        hold = random_delay(timing.hold_ms)
        adapter.press(key, hold)
        events.append({"type": "press", "index": index, "key": key_name, "hold_sec": round(hold, 4)})

        if index != len(keys) - 1:
            delay = random_delay(timing.between_ms)
            if random.random() < timing.long_pause_chance:
                delay += random_delay(timing.long_pause_ms)
                pause_type = "long_between"
            else:
                pause_type = "between"
            cancelable_sleep(delay, cancel_event)
            events.append({"type": pause_type, "sec": round(delay, 4)})
    return events


def type_text_as_physical_keys(
    text: str,
    dry_run: bool,
    timing: HumanTiming,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    adapter: InputAdapter = DryRunInputAdapter() if dry_run else KEYBOARD_ADAPTER
    keys = text_to_physical_keys(text)
    events: list[dict[str, Any]] = []
    desired_ime_open: bool | None = None

    initial_delay = random_delay(timing.initial_delay_ms)
    cancelable_sleep(initial_delay, cancel_event)
    events.append({"type": "initial_delay", "sec": round(initial_delay, 4)})

    key_index = 0
    for char in text:
        if cancel_event is not None and cancel_event.is_set():
            events.append({"type": "cancelled", "index": key_index})
            break
        mode = text_char_ime_mode(char)
        if mode is not None and mode != desired_ime_open:
            desired_ime_open = mode
            if dry_run:
                switched = True
            else:
                switched = set_ime_open_status(mode)
            events.append({"type": "ime_switch", "open": mode, "ok": switched})

        for key in char_to_physical_keys(char):
            if cancel_event is not None and cancel_event.is_set():
                events.append({"type": "cancelled", "index": key_index})
                break
            hold = random_delay(timing.hold_ms)
            adapter.press(key, hold)
            events.append({"type": "press", "index": key_index, "key": key.lower(), "hold_sec": round(hold, 4)})
            key_index += 1

            if key_index != len(keys):
                delay = random_delay(timing.between_ms)
                if random.random() < timing.long_pause_chance:
                    delay += random_delay(timing.long_pause_ms)
                    pause_type = "long_between"
                else:
                    pause_type = "between"
                cancelable_sleep(delay, cancel_event)
                events.append({"type": pause_type, "sec": round(delay, 4)})

    return {"keys": keys, "events": events}


def split_key_chord(key: str) -> tuple[list[str], str]:
    modifiers: list[str] = []
    if "+" in key:
        parts = key.split("+")
        modifiers = parts[:-1]
        key_name = parts[-1]
    elif len(key) == 1 and key.isalpha() and key.isupper():
        modifiers = ["shift"]
        key_name = key.lower()
    else:
        key_name = key
    return modifiers, key_name


def key_to_vk(key: str) -> int:
    normalized = key.lower() if len(key) == 1 and key.isalpha() else key
    if normalized in VK_CODES:
        return VK_CODES[normalized]
    raise ValueError(f"Unsupported SendInput key: {key}")


def cancelable_sleep(duration: float, cancel_event: threading.Event | None) -> None:
    if cancel_event is None:
        time.sleep(duration)
        return
    cancel_event.wait(duration)


def text_to_physical_keys(text: str) -> list[str]:
    sequence: list[str] = []
    for char in text:
        sequence.extend(char_to_physical_keys(char))
    return sequence


def char_to_physical_keys(char: str) -> list[str]:
    code = ord(char)
    if HANGUL_BASE <= code <= HANGUL_END:
        offset = code - HANGUL_BASE
        choseong = offset // (HANGUL_JUNG_COUNT * HANGUL_JONG_COUNT)
        jungseong = (offset % (HANGUL_JUNG_COUNT * HANGUL_JONG_COUNT)) // HANGUL_JONG_COUNT
        jongseong = offset % HANGUL_JONG_COUNT
        return list(CHOSEONG_KEYS[choseong] + JUNGSEONG_KEYS[jungseong] + JONGSEONG_KEYS[jongseong])
    if char in COMPAT_JAMO_KEYS:
        return list(COMPAT_JAMO_KEYS[char])
    if char == " ":
        return ["space"]
    if char in SPECIAL_TEXT_KEYS:
        return [SPECIAL_TEXT_KEYS[char]]
    if char in SHIFTED_ASCII_KEYS:
        return [SHIFTED_ASCII_KEYS[char]]
    if char.isascii():
        return [char]
    raise ValueError(f"Unsupported character for physical key typing: {char}")


def text_char_ime_mode(char: str) -> bool | None:
    code = ord(char)
    if HANGUL_BASE <= code <= HANGUL_END or char in COMPAT_JAMO_KEYS:
        return True
    if char.isascii() and char != " ":
        return False
    return None


def contains_hangul(text: str) -> bool:
    return any(HANGUL_BASE <= ord(char) <= HANGUL_END or char in COMPAT_JAMO_KEYS for char in text)


def get_input_state() -> dict[str, Any]:
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        imm32 = ctypes.WinDLL("imm32", use_last_error=True)

        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, None)
        layout = user32.GetKeyboardLayout(thread_id)
        lang_id = layout & 0xFFFF

        ime_hwnd = imm32.ImmGetDefaultIMEWnd(hwnd)
        ime_open = bool(user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0)) if ime_hwnd else False
        conversion_mode = int(user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0)) if ime_hwnd else None
        is_korean_layout = lang_id == LANG_KOREAN
        return {
            "foreground_hwnd": int(hwnd),
            "keyboard_layout_hex": f"0x{layout & 0xFFFFFFFF:08x}",
            "lang_id_hex": f"0x{lang_id:04x}",
            "is_korean_layout": is_korean_layout,
            "ime_hwnd": int(ime_hwnd) if ime_hwnd else 0,
            "ime_open": ime_open,
            "conversion_mode": conversion_mode,
            "is_korean_ime_ready": is_korean_layout and ime_open,
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "is_korean_ime_ready": False,
        }


def set_ime_open_status(opened: bool) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    imm32 = ctypes.WinDLL("imm32", use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    ime_hwnd = imm32.ImmGetDefaultIMEWnd(hwnd)
    if not ime_hwnd:
        return False
    user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, 1 if opened else 0)
    time.sleep(0.03)
    return bool(user32.SendMessageW(ime_hwnd, WM_IME_CONTROL, IMC_GETOPENSTATUS, 0)) == opened


def provider_capabilities() -> dict[str, Any]:
    return {
        "window": {
            "default": "pywinctl",
            "providers": {
                "pywinctl": module_capability(["pywinctl"]),
                "builtin": {"available": True, "implemented": True, "module": None},
            },
        },
        "input": {
            "default": "builtin",
            "providers": {
                "builtin": {
                    "available": True,
                    "implemented": True,
                    "supports_scan_codes": False,
                    "adapter": KEYBOARD_ADAPTER.name,
                },
                "pydirectinput": {
                    **module_capability(["pydirectinput", "pydirectinput_rgx"]),
                    "supports_scan_codes": True,
                    "adapter": "pydirectinput",
                },
            },
        },
        "capture": {
            "default": "mss",
            "providers": {
                "mss": {"available": True, "implemented": True, "module": "mss"},
                "dxcam": module_capability(["dxcam"]),
                "windows_capture": {
                    **module_capability(["windows_capture"]),
                    "implemented": False,
                    "note": "experimental provider candidate; not used as a default path",
                },
            },
        },
        "accessibility": {
            "pywinauto": module_capability(["pywinauto"]),
        },
    }


def module_capability(module_names: list[str]) -> dict[str, Any]:
    for module_name in module_names:
        spec = importlib.util.find_spec(module_name)
        if spec is not None:
            return {"available": True, "implemented": True, "module": module_name}
    return {"available": False, "implemented": True, "module": module_names[0], "error": "not installed"}


def normalize_input_provider(provider: str) -> str:
    normalized = provider.lower().strip()
    if normalized not in INPUT_PROVIDERS:
        raise ValueError(f"unsupported input provider: {provider}")
    return normalized


def normalize_capture_provider(provider: str) -> str:
    normalized = provider.lower().strip()
    if normalized not in CAPTURE_PROVIDERS:
        raise ValueError(f"unsupported capture provider: {provider}")
    return normalized


def normalize_window_provider(provider: str) -> str:
    normalized = provider.lower().strip()
    if normalized not in WINDOW_PROVIDERS:
        raise ValueError(f"unsupported window provider: {provider}")
    return normalized


def load_pydirectinput() -> Any:
    errors = []
    for module_name in ("pydirectinput", "pydirectinput_rgx"):
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    raise RuntimeError("pydirectinput provider is unavailable: " + "; ".join(errors))


def get_input_adapter(provider: str, dry_run: bool) -> InputAdapter:
    normalized = normalize_input_provider(provider)
    if dry_run:
        return DryRunInputAdapter()
    if normalized == "builtin":
        return KEYBOARD_ADAPTER
    global PYDIRECTINPUT_ADAPTER
    if PYDIRECTINPUT_ADAPTER is None:
        PYDIRECTINPUT_ADAPTER = PyDirectInputAdapter()
    return PYDIRECTINPUT_ADAPTER


def selected_input_adapter_name(dry_run: bool, provider: str) -> str:
    if dry_run:
        normalize_input_provider(provider)
        return "dry-run"
    return get_input_adapter(provider, dry_run=False).name


def normalize_pydirectinput_key(key: str) -> str:
    normalized = key.lower() if len(key) == 1 and key.isalpha() else key.lower()
    aliases = {
        "ctrl": "ctrl",
        "control": "ctrl",
        "alt": "alt",
        "shift": "shift",
        "space": "space",
        "enter": "enter",
        "backspace": "backspace",
    }
    return aliases.get(normalized, normalized)


def capture_region_dxcam(monitor_index: int, region: dict[str, int]) -> Image.Image:
    dxcam = importlib.import_module("dxcam")
    output_idx = max(0, monitor_index - 1)
    camera = dxcam.create(output_idx=output_idx, output_color="RGB")
    box = (
        int(region["left"]),
        int(region["top"]),
        int(region["left"] + region["width"]),
        int(region["top"] + region["height"]),
    )
    frame = camera.grab(region=box)
    if frame is None:
        raise RuntimeError("dxcam returned no frame")
    return Image.fromarray(frame)


def capture_metadata(
    provider: str,
    monitor: int,
    roi: Roi | None,
    region: dict[str, int],
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "monitor": monitor,
        "roi": [roi.left, roi.top, roi.right, roi.bottom] if roi else None,
        "full_monitor": roi is None and target is None,
        "region": dict(region),
        "target": target,
    }


def get_selected_target_id() -> str | None:
    with selected_target_lock:
        return selected_target_id


def set_selected_target_id(target_id: str | None) -> None:
    global selected_target_id
    with selected_target_lock:
        selected_target_id = target_id


def list_window_targets(provider: str = "auto") -> tuple[str, list[dict[str, Any]], str | None]:
    provider_name = normalize_window_provider(provider)
    fallback_error: str | None = None
    if provider_name in {"auto", "pywinctl"}:
        try:
            targets = list_pywinctl_targets()
            return "pywinctl", targets, None
        except Exception as exc:
            fallback_error = str(exc)
            if provider_name == "pywinctl":
                return "pywinctl", [], fallback_error
    return "builtin", list_builtin_targets(), fallback_error


def select_target(request: TargetSelectRequest) -> dict[str, Any] | None:
    if request.target_id:
        target = get_target_by_id(request.target_id)
        if target:
            set_selected_target_id(str(target["target_id"]))
        return target
    if request.window_id is not None:
        target = get_target_by_id(f"hwnd:{int(request.window_id)}")
        if target:
            set_selected_target_id(str(target["target_id"]))
        return target
    provider_name, targets, _ = list_window_targets(request.provider)
    title_contains = request.title_contains.lower().strip() if request.title_contains else None
    if title_contains:
        targets = [target for target in targets if title_contains in str(target.get("title", "")).lower()]
    target = targets[0] if targets else None
    if target:
        target["selected_via_provider"] = provider_name
        set_selected_target_id(str(target["target_id"]))
    return target


def get_selected_target() -> dict[str, Any] | None:
    target_id = get_selected_target_id()
    if target_id:
        return get_target_by_id(target_id)
    hwnd = int(ctypes.WinDLL("user32", use_last_error=True).GetForegroundWindow())
    return target_from_hwnd(hwnd, provider="builtin")


def get_target_by_id(target_id: str | None) -> dict[str, Any] | None:
    if not target_id:
        return None
    if target_id.startswith("hwnd:"):
        try:
            hwnd = int(target_id.split(":", 1)[1])
        except ValueError:
            return {"target_id": target_id, "is_stale": True, "error": "invalid hwnd target id"}
        return target_from_hwnd(hwnd, provider="builtin")
    return {"target_id": target_id, "is_stale": True, "error": "unsupported target id"}


def activate_target(target_id: str) -> bool:
    target = get_target_by_id(target_id)
    if not target or target.get("is_stale"):
        return False
    hwnd = int(target["window_id"])
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
    return bool(user32.SetForegroundWindow(wintypes.HWND(hwnd)))


def list_builtin_targets() -> list[dict[str, Any]]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    targets: list[dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: wintypes.HWND, _lparam: wintypes.LPARAM) -> bool:
        target = target_from_hwnd(int(hwnd), provider="builtin")
        if target and not target.get("is_stale") and target.get("title"):
            targets.append(target)
        return True

    user32.EnumWindows(callback, 0)
    return targets


def list_pywinctl_targets() -> list[dict[str, Any]]:
    pywinctl = importlib.import_module("pywinctl")
    active = pywinctl.getActiveWindow() if hasattr(pywinctl, "getActiveWindow") else None
    active_hwnd = pywinctl_window_id(active) if active is not None else None
    targets: list[dict[str, Any]] = []
    for window in pywinctl.getAllWindows():
        target = target_from_pywinctl(window, active_hwnd)
        if target and target.get("title"):
            targets.append(target)
    return targets


def target_from_pywinctl(window: Any, active_hwnd: int | None) -> dict[str, Any] | None:
    hwnd = pywinctl_window_id(window)
    if hwnd is not None:
        target = target_from_hwnd(hwnd, provider="pywinctl")
        if target:
            target["is_active"] = hwnd == active_hwnd if active_hwnd is not None else target["is_active"]
        return target
    title = str(getattr(window, "title", "") or "")
    bounds = pywinctl_bounds(window)
    if not title or not bounds:
        return None
    target_id = f"pywinctl:{abs(hash((title, bounds['left'], bounds['top'], bounds['width'], bounds['height'])))}"
    return {
        "target_id": target_id,
        "provider": "pywinctl",
        "window_id": None,
        "title": title,
        "bounds": bounds,
        "is_active": False,
        "is_stale": False,
    }


def pywinctl_window_id(window: Any) -> int | None:
    if window is None:
        return None
    for attr in ("hWnd", "_hWnd", "handle", "_handle"):
        value = getattr(window, attr, None)
        if value:
            return int(value)
    for method in ("getHandle", "getHWND"):
        func = getattr(window, method, None)
        if callable(func):
            value = func()
            if value:
                return int(value)
    return None


def pywinctl_bounds(window: Any) -> dict[str, int] | None:
    try:
        left = int(getattr(window, "left"))
        top = int(getattr(window, "top"))
        width = int(getattr(window, "width"))
        height = int(getattr(window, "height"))
    except Exception:
        box = getattr(window, "box", None)
        if box is None:
            return None
        try:
            left, top, width, height = [int(item) for item in box]
        except Exception:
            return None
    return {"left": left, "top": top, "width": width, "height": height}


def target_from_hwnd(hwnd: int, provider: str) -> dict[str, Any] | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    if not hwnd or not bool(user32.IsWindow(wintypes.HWND(hwnd))):
        return {"target_id": f"hwnd:{hwnd}", "provider": provider, "window_id": hwnd, "is_stale": True}
    visible = bool(user32.IsWindowVisible(wintypes.HWND(hwnd)))
    title = window_title(hwnd)
    bounds = window_bounds(hwnd)
    foreground = int(user32.GetForegroundWindow())
    stale = not visible or bounds is None or bounds["width"] <= 0 or bounds["height"] <= 0
    return {
        "target_id": f"hwnd:{hwnd}",
        "provider": provider,
        "window_id": hwnd,
        "title": title,
        "bounds": bounds,
        "is_active": hwnd == foreground,
        "is_visible": visible,
        "is_stale": stale,
    }


def window_title(hwnd: int) -> str:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    length = int(user32.GetWindowTextLengthW(wintypes.HWND(hwnd)))
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wintypes.HWND(hwnd), buffer, length + 1)
    return buffer.value


def window_bounds(hwnd: int) -> dict[str, int] | None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def daemon_capabilities() -> dict[str, str]:
    return {
        "keyboard": "active",
        "screen_capture": "active",
        "mouse": "planned",
        "microphone": "planned",
        "camera": "planned",
        "background": "planned",
    }


def privilege_status() -> dict[str, Any]:
    try:
        is_admin = bool(ctypes.WinDLL("shell32", use_last_error=True).IsUserAnAdmin())
    except Exception as exc:
        return {"is_admin": False, "error": str(exc)}
    return {"is_admin": is_admin}


def random_delay(bounds_ms: tuple[int, int]) -> float:
    low, high = bounds_ms
    if high < low:
        low, high = high, low
    return random.uniform(low / 1000.0, high / 1000.0)


def monitor_to_region(monitor: dict[str, int], roi: Roi | None) -> dict[str, int]:
    if roi is None:
        return dict(monitor)
    return {
        "left": monitor["left"] + int(monitor["width"] * roi.left),
        "top": monitor["top"] + int(monitor["height"] * roi.top),
        "width": int(monitor["width"] * (roi.right - roi.left)),
        "height": int(monitor["height"] * (roi.bottom - roi.top)),
    }


def encode_image(image: Image.Image, fmt: str, **kwargs: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "asdw_fusion.windows_capture_daemon:app",
        host="127.0.0.1",
        port=7870,
        reload=False,
    )
