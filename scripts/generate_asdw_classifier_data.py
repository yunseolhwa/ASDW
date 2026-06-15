from __future__ import annotations

import argparse
import random
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image


PROJECT = (
    Path("/mnt/d/asdw-fusion-typer")
    if Path("/mnt/d/asdw-fusion-typer").exists()
    else Path("D:/asdw-fusion-typer")
)
SOURCE = (
    Path(
        "/mnt/c/Users/ROCmAdmin/AppData/Local/Temp/"
        "codex-clipboard-e3946a09-fd69-4065-a92f-0ab5ef4aa79e.png"
    )
    if Path("/mnt/c/Users/ROCmAdmin/AppData/Local/Temp").exists()
    else Path(
        "C:/Users/ROCmAdmin/AppData/Local/Temp/"
        "codex-clipboard-e3946a09-fd69-4065-a92f-0ab5ef4aa79e.png"
    )
)
ROI_FRAC = (0.34, 0.46, 0.66, 0.57)
KEYS = ("A", "S", "D", "W")
DEFAULT_SEQUENCE = "SDWWDWDAA"

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import find_button_boxes  # noqa: E402
from scripts.make_augmented_stress_views import augment_button_crop  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic ASDW crop dataset.")
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=PROJECT / "data" / "asdw_classifier")
    parser.add_argument("--sequence", default=DEFAULT_SEQUENCE)
    parser.add_argument("--train-per-class", type=int, default=420)
    parser.add_argument("--val-per-class", type=int, default=120)
    parser.add_argument("--clean-per-class", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20260616)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    image = Image.open(args.source).convert("RGB")
    roi = crop_roi(image, ROI_FRAC)
    boxes = find_button_boxes(roi)
    if len(boxes) != len(args.sequence):
        raise RuntimeError(f"Expected {len(args.sequence)} boxes, found {len(boxes)}")

    if args.output.exists():
        shutil.rmtree(args.output)

    base_crops: dict[str, list[Image.Image]] = {key: [] for key in KEYS}
    source_dir = args.output / "source_crops"
    source_dir.mkdir(parents=True, exist_ok=True)
    for index, (box, label) in enumerate(zip(boxes, args.sequence, strict=True), start=1):
        crop = roi.crop(box)
        base_crops[label].append(crop)
        crop.save(source_dir / f"{index:02d}_{label}.png")

    for split, count in (("train", args.train_per_class), ("val", args.val_per_class)):
        for label in KEYS:
            out_dir = args.output / split / label
            out_dir.mkdir(parents=True, exist_ok=True)
            choices = base_crops[label]
            if not choices:
                raise RuntimeError(f"No source crops for label {label}")
            if split == "train":
                for clean_index in range(args.clean_per_class):
                    normalized = normalize_clean_crop(random.choice(choices))
                    normalized.save(out_dir / f"{label}_clean_{clean_index:04d}.png")
            for sample_index in range(count):
                base = random.choice(choices)
                aug = augment_button_crop(base)
                aug.save(out_dir / f"{label}_{sample_index:04d}.png")

    print(f"dataset={args.output}")
    print(f"boxes={len(boxes)} sequence={args.sequence}")
    train_total = (args.train_per_class + args.clean_per_class) * len(KEYS)
    print(f"train={train_total} val={args.val_per_class * len(KEYS)}")
    return 0


def crop_roi(image: Image.Image, roi_frac: tuple[float, float, float, float]) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = roi_frac
    return image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    )


def normalize_clean_crop(image: Image.Image, size: int = 112) -> Image.Image:
    side = max(image.size)
    canvas = Image.new("RGB", (side, side), (32, 24, 28))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas.resize((size, size), Image.Resampling.BICUBIC)


if __name__ == "__main__":
    raise SystemExit(main())
