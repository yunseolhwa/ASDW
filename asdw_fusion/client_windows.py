from __future__ import annotations

import argparse
import base64
import ctypes
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import mss
import requests
from PIL import Image, ImageDraw


KEYS = {"A", "S", "D", "W"}
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong
VK_CODES = {letter: 0x41 + index for index, letter in enumerate("abcdefghijklmnopqrstuvwxyz")}


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


@dataclass
class Roi:
    left: float
    top: float
    right: float
    bottom: float

    @classmethod
    def from_values(cls, values: list[float]) -> "Roi":
        if len(values) != 4:
            raise ValueError("--roi-frac needs four values: left top right bottom")
        left, top, right, bottom = values
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("--roi-frac values must be normalized fractions")
        return cls(left, top, right, bottom)


class SendInputKeySender:
    def __init__(self, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)

    def press(self, key: str) -> None:
        if key.upper() not in KEYS:
            return
        key_name = key.lower()
        if self.dry_run:
            print(f"[dry-run] press {key.lower()}")
            return
        self._send(key_name, key_up=False)
        self._send(key_name, key_up=True)

    def _send(self, key: str, key_up: bool) -> None:
        vk = VK_CODES[key]
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture the centered ASDW prompt and press predicted keys.",
    )
    parser.add_argument("--server", default="http://127.0.0.1:7868/predict")
    parser.add_argument("--monitor", type=int, default=1)
    parser.add_argument(
        "--roi-frac",
        nargs=4,
        type=float,
        default=[0.34, 0.46, 0.66, 0.57],
        metavar=("L", "T", "R", "B"),
        help="Normalized screen crop. Default targets the lower-center prompt row.",
    )
    parser.add_argument(
        "--sensors",
        default="template,classifier",
        help="Comma-separated sensors sent to the server.",
    )
    parser.add_argument("--interval", type=float, default=0.08)
    parser.add_argument("--key-delay", type=float, default=0.045)
    parser.add_argument("--repeat-cooldown", type=float, default=0.75)
    parser.add_argument("--min-confidence", type=float, default=0.35)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument(
        "--live-input",
        action="store_false",
        dest="dry_run",
        help="Actually press keys. Use only in an allowed test environment.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--debug-dir", type=Path)
    parser.add_argument("--draw-debug", action="store_true")
    args = parser.parse_args()

    roi = Roi.from_values(args.roi_frac)
    sender = SendInputKeySender(args.dry_run)
    sensors = [item.strip() for item in args.sensors.split(",") if item.strip()]

    last_sequence = ""
    last_sent = 0.0
    with mss.mss() as screen:
        monitor = screen.monitors[args.monitor]
        while True:
            frame = capture_roi(screen, monitor, roi)
            prediction = predict(args.server, frame, sensors=sensors, debug=bool(args.debug_dir))
            detections = prediction.get("detections", [])
            sequence = "".join(
                item["key"]
                for item in detections
                if item.get("confidence", 0.0) >= args.min_confidence
            )
            if sequence:
                print(
                    json.dumps(
                        {
                            "sequence": sequence,
                            "latency_ms": prediction.get("latency_ms"),
                            "device": prediction.get("device"),
                            "dry_run": args.dry_run,
                        },
                        ensure_ascii=False,
                    )
                )
            now = time.monotonic()
            if sequence and should_send(sequence, last_sequence, last_sent, now, args.repeat_cooldown):
                for key in sequence:
                    sender.press(key)
                    time.sleep(args.key_delay)
                last_sequence = sequence
                last_sent = now
            if args.debug_dir:
                save_debug(args.debug_dir, frame, prediction, draw=args.draw_debug)
            if args.once:
                break
            time.sleep(args.interval)
    return 0


def capture_roi(screen: mss.mss, monitor: dict[str, int], roi: Roi) -> Image.Image:
    left = monitor["left"] + int(monitor["width"] * roi.left)
    top = monitor["top"] + int(monitor["height"] * roi.top)
    width = int(monitor["width"] * (roi.right - roi.left))
    height = int(monitor["height"] * (roi.bottom - roi.top))
    shot = screen.grab({"left": left, "top": top, "width": width, "height": height})
    return Image.frombytes("RGB", shot.size, shot.rgb)


def predict(server_url: str, image: Image.Image, sensors: list[str], debug: bool) -> dict[str, Any]:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    payload = {
        "image_b64": base64.b64encode(buffer.getvalue()).decode("ascii"),
        "sensors": sensors,
        "debug": debug,
    }
    response = requests.post(server_url, json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def should_send(
    sequence: str,
    last_sequence: str,
    last_sent: float,
    now: float,
    cooldown: float,
) -> bool:
    if sequence != last_sequence:
        return True
    return now - last_sent >= cooldown


def save_debug(debug_dir: Path, image: Image.Image, prediction: dict[str, Any], draw: bool) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    millis = int((time.time() % 1) * 1000)
    base = debug_dir / f"{stamp}-{millis:03d}"
    if draw:
        image = image.copy()
        drawer = ImageDraw.Draw(image)
        for item in prediction.get("detections", []):
            box = tuple(item.get("box", (0, 0, 0, 0)))
            label = f"{item.get('key')} {item.get('confidence', 0):.2f}"
            drawer.rectangle(box, outline=(255, 255, 0), width=2)
            drawer.text((box[0], max(0, box[1] - 12)), label, fill=(255, 255, 0))
    image.save(base.with_suffix(".png"))
    base.with_suffix(".json").write_text(json.dumps(prediction, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
