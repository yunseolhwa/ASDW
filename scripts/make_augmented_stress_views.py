from __future__ import annotations

import io
import random
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


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
TRUE_SEQUENCE = "SDWWDWDAA"
RANDOM_SEED = 42

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import find_button_boxes  # noqa: E402


def main() -> None:
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    image = Image.open(SOURCE).convert("RGB")
    roi = crop_roi(image, ROI_FRAC)
    boxes = find_button_boxes(roi)

    detection_tiles = []
    for index in range(12):
        aug = augment_full_roi(roi, severity=0.45 + index * 0.045)
        detected = find_button_boxes(aug)
        detection_tiles.append(draw_detection_tile(aug, detected, index + 1))

    training_tiles = []
    for box_index, (box, label) in enumerate(zip(boxes, TRUE_SEQUENCE, strict=False)):
        crop = roi.crop(box)
        for sample_index in range(4):
            aug = augment_button_crop(crop)
            training_tiles.append(draw_training_tile(aug, label, box_index + 1, sample_index + 1))

    detection_grid = make_grid(detection_tiles, columns=3, title="Full ROI stress test: current detector after destructive augmentation")
    training_grid = make_grid(training_tiles, columns=9, title="Training-style per-button augmentation samples")

    detection_path = PROJECT / "augmentation-detection-stress.png"
    training_path = PROJECT / "augmentation-training-samples.png"
    detection_grid.save(detection_path)
    training_grid.save(training_path)

    print(detection_path)
    print(training_path)


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


def augment_full_roi(image: Image.Image, severity: float) -> Image.Image:
    width, height = image.size
    canvas = Image.new("RGB", image.size, random_bg_color())

    scaled = resize_keep_center(
        image,
        scale=random.uniform(0.65, 1.55) * (1 + severity * random.uniform(-0.25, 0.35)),
    )
    scaled = scaled.rotate(
        random.uniform(-18, 18) * severity,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=random_bg_color(),
    )
    scaled = perspective_warp(scaled, max_jitter=0.055 * severity)
    scaled = color_jitter(scaled, severity)
    scaled = add_noise_and_artifacts(scaled, severity)

    x = int((width - scaled.width) / 2 + random.uniform(-width * 0.17, width * 0.17) * severity)
    y = int((height - scaled.height) / 2 + random.uniform(-height * 0.30, height * 0.30) * severity)
    canvas.paste(scaled, (x, y))
    canvas = add_occluders(canvas, count=random.randint(1, 4), severity=severity)
    canvas = add_scanlines(canvas, severity)
    return canvas


def augment_button_crop(image: Image.Image) -> Image.Image:
    severity = random.uniform(0.55, 1.0)
    crop = pad_to_square(image, pad_ratio=random.uniform(0.10, 0.35), fill=random_bg_color())
    crop = resize_keep_center(crop, scale=random.uniform(0.65, 1.75))
    crop = crop.rotate(
        random.uniform(-32, 32),
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=random_bg_color(),
    )
    crop = perspective_warp(crop, max_jitter=random.uniform(0.02, 0.12))
    crop = color_jitter(crop, severity)
    crop = add_noise_and_artifacts(crop, severity)
    crop = add_occluders(crop, count=random.randint(0, 3), severity=severity)
    crop.thumbnail((96, 96), Image.Resampling.LANCZOS)
    tile = Image.new("RGB", (112, 112), random_bg_color())
    tile.paste(crop, ((112 - crop.width) // 2, (112 - crop.height) // 2))
    return tile


def resize_keep_center(image: Image.Image, scale: float) -> Image.Image:
    width, height = image.size
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(new_size, Image.Resampling.BICUBIC)


def pad_to_square(image: Image.Image, pad_ratio: float, fill: tuple[int, int, int]) -> Image.Image:
    size = max(image.size)
    pad = int(size * pad_ratio)
    canvas = Image.new("RGB", (size + pad * 2, size + pad * 2), fill)
    canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
    return canvas


def perspective_warp(image: Image.Image, max_jitter: float) -> Image.Image:
    arr = np.asarray(image)
    h, w = arr.shape[:2]
    jitter_x = int(w * max_jitter)
    jitter_y = int(h * max_jitter)
    if jitter_x <= 0 or jitter_y <= 0:
        return image

    src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    dst = np.float32(
        [
            [random.randint(0, jitter_x), random.randint(0, jitter_y)],
            [w - 1 - random.randint(0, jitter_x), random.randint(0, jitter_y)],
            [w - 1 - random.randint(0, jitter_x), h - 1 - random.randint(0, jitter_y)],
            [random.randint(0, jitter_x), h - 1 - random.randint(0, jitter_y)],
        ]
    )
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(
        arr,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REFLECT_101,
    )
    return Image.fromarray(warped)


def color_jitter(image: Image.Image, severity: float) -> Image.Image:
    image = ImageEnhance.Brightness(image).enhance(random.uniform(0.55, 1.45))
    image = ImageEnhance.Contrast(image).enhance(random.uniform(0.55, 1.75))
    image = ImageEnhance.Color(image).enhance(random.uniform(0.35, 1.85))
    image = ImageEnhance.Sharpness(image).enhance(random.uniform(0.25, 2.4))
    if random.random() < 0.45:
        image = image.filter(ImageFilter.GaussianBlur(radius=random.uniform(0.2, 1.4) * severity))
    return image


def add_noise_and_artifacts(image: Image.Image, severity: float) -> Image.Image:
    arr = np.asarray(image).astype(np.float32)
    noise_std = random.uniform(6, 42) * severity
    arr += np.random.normal(0, noise_std, arr.shape)

    if random.random() < 0.65:
        mask = np.random.rand(arr.shape[0], arr.shape[1])
        salt = mask < 0.006 * severity
        pepper = mask > 1 - 0.006 * severity
        arr[salt] = 255
        arr[pepper] = 0

    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr)

    if random.random() < 0.70:
        buffer = io.BytesIO()
        out.save(buffer, format="JPEG", quality=random.randint(24, 68))
        out = Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")
    return out


def add_occluders(image: Image.Image, count: int, severity: float) -> Image.Image:
    out = image.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    width, height = out.size
    for _ in range(count):
        x1 = random.randint(0, max(1, width - 1))
        y1 = random.randint(0, max(1, height - 1))
        x2 = x1 + random.randint(int(width * 0.04), int(width * 0.18))
        y2 = y1 + random.randint(int(height * 0.05), int(height * 0.28))
        color = (*random_bg_color(), random.randint(65, int(160 * severity)))
        draw.rectangle((x1, y1, x2, y2), fill=color)
    return out


def add_scanlines(image: Image.Image, severity: float) -> Image.Image:
    out = image.copy()
    draw = ImageDraw.Draw(out, "RGBA")
    step = random.randint(3, 8)
    alpha = int(24 * severity)
    for y in range(0, out.height, step):
        draw.line((0, y, out.width, y), fill=(0, 0, 0, alpha), width=1)
    return out


def draw_detection_tile(image: Image.Image, boxes: list[tuple[int, int, int, int]], index: int) -> Image.Image:
    tile = image.copy()
    draw = ImageDraw.Draw(tile)
    font = load_font(16)
    for box_index, box in enumerate(boxes, 1):
        draw.rectangle(box, outline=(255, 232, 0), width=3)
        draw.text((box[0] + 3, box[1] + 3), str(box_index), fill=(255, 232, 0), font=font)
    draw.rectangle((0, 0, tile.width - 1, tile.height - 1), outline=(70, 74, 82), width=2)
    draw.text((8, 8), f"#{index} boxes={len(boxes)}", fill=(255, 255, 255), font=font)
    return tile


def draw_training_tile(image: Image.Image, label: str, box_index: int, sample_index: int) -> Image.Image:
    tile = image.copy()
    draw = ImageDraw.Draw(tile)
    font = load_font(17)
    draw.rectangle((0, 0, tile.width - 1, tile.height - 1), outline=(255, 232, 0), width=2)
    draw.text((5, 4), f"{box_index}:{label}", fill=(255, 255, 255), font=font)
    draw.text((72, 88), f"v{sample_index}", fill=(255, 232, 0), font=font)
    return tile


def make_grid(tiles: list[Image.Image], columns: int, title: str) -> Image.Image:
    font = load_font(22)
    tile_w = max(tile.width for tile in tiles)
    tile_h = max(tile.height for tile in tiles)
    rows = (len(tiles) + columns - 1) // columns
    pad = 14
    header = 44
    canvas = Image.new(
        "RGB",
        (columns * tile_w + (columns + 1) * pad, rows * tile_h + (rows + 1) * pad + header),
        (22, 24, 28),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 12), title, fill=(255, 255, 255), font=font)
    for idx, tile in enumerate(tiles):
        row = idx // columns
        col = idx % columns
        x = pad + col * (tile_w + pad)
        y = header + pad + row * (tile_h + pad)
        canvas.paste(tile, (x, y))
    return canvas


def random_bg_color() -> tuple[int, int, int]:
    base = random.choice(
        [
            (18, 22, 27),
            (45, 18, 25),
            (90, 21, 24),
            (24, 54, 72),
            (88, 72, 34),
            (12, 60, 42),
        ]
    )
    return tuple(int(np.clip(channel + random.randint(-18, 18), 0, 255)) for channel in base)


def load_font(size: int) -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


if __name__ == "__main__":
    main()
