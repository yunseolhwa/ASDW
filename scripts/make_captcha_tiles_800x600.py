from __future__ import annotations

import argparse
import json
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
ORIGINAL_SEQUENCE = "SDWWDWDAA"
KEYS = ("A", "S", "D", "W")

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import find_button_boxes  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create ASDW prompt-like 800x600 tiles.")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260616)
    parser.add_argument("--output", type=Path, default=PROJECT / "captcha_tiles_800x600")
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)

    args.output.mkdir(parents=True, exist_ok=True)
    for old in args.output.glob("*.png"):
        old.unlink()
    for old in args.output.glob("*.json"):
        old.unlink()

    image = Image.open(SOURCE).convert("RGB")
    roi = crop_roi(image)
    boxes = find_button_boxes(roi)
    crops = [(label, roi.crop(box)) for label, box in zip(ORIGINAL_SEQUENCE, boxes, strict=True)]

    metadata = []
    preview_tiles = []
    for index in range(1, args.count + 1):
        canvas, row = make_sample(crops, args.width, args.height, index)
        path = args.output / f"captcha_{index:03d}_{row['sequence']}.png"
        canvas.save(path)
        row["file"] = path.name
        metadata.append(row)
        if index <= 12:
            preview_tiles.append(canvas.resize((240, 180), Image.Resampling.LANCZOS))

    (args.output / "labels.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    preview = make_preview(preview_tiles)
    preview_path = PROJECT / "captcha_tiles_800x600_preview.png"
    preview.save(preview_path)
    print(f"output_dir={args.output}")
    print(f"preview={preview_path}")
    print(f"count={len(metadata)}")
    return 0


def crop_roi(image: Image.Image) -> Image.Image:
    width, height = image.size
    left, top, right, bottom = ROI_FRAC
    return image.crop(
        (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
    )


def make_sample(
    crops: list[tuple[str, Image.Image]],
    width: int,
    height: int,
    index: int,
) -> tuple[Image.Image, dict]:
    shuffled = crops[:]
    random.shuffle(shuffled)
    sequence = "".join(label for label, _ in shuffled)
    canvas = make_noisy_background(width, height)
    draw = ImageDraw.Draw(canvas, "RGBA")
    font = load_font(18)

    tile_cols = random.choice([4, 5, 6, 8])
    tile_rows = random.choice([3, 4, 5, 6])
    add_tile_warp_background(canvas, tile_cols, tile_rows)

    row_y = random.randint(210, 360)
    total_span = random.randint(560, 720)
    start_x = (width - total_span) // 2 + random.randint(-35, 35)
    step = total_span / max(len(shuffled) - 1, 1)
    objects = []

    for object_index, (label, crop) in enumerate(shuffled, start=1):
        scale = random.uniform(0.50, 1.50)
        angle = random.uniform(-35, 35)
        x = int(start_x + (object_index - 1) * step + random.randint(-16, 16))
        y = int(row_y + random.randint(-45, 45))
        transformed = transform_button(crop, scale, angle)
        paste_x = x - transformed.width // 2
        paste_y = y - transformed.height // 2
        canvas.paste(transformed, (paste_x, paste_y), transformed if transformed.mode == "RGBA" else None)
        bbox = [paste_x, paste_y, paste_x + transformed.width, paste_y + transformed.height]
        objects.append(
            {
                "index": object_index,
                "label": label,
                "scale": round(scale, 4),
                "angle": round(angle, 3),
                "bbox_xyxy": bbox,
            }
        )

    add_captcha_noise(canvas)
    add_cut_tiles_overlay(canvas, tile_cols, tile_rows)
    add_random_text_fragments(draw, font, width, height)
    canvas = final_degrade(canvas)

    row = {
        "id": index,
        "sequence": sequence,
        "width": width,
        "height": height,
        "tile_cols": tile_cols,
        "tile_rows": tile_rows,
        "objects": objects,
    }
    return canvas, row


def transform_button(crop: Image.Image, scale: float, angle: float) -> Image.Image:
    pad = int(max(crop.size) * 0.25)
    padded = Image.new("RGBA", (crop.width + pad * 2, crop.height + pad * 2), (0, 0, 0, 0))
    padded.paste(crop.convert("RGBA"), (pad, pad))
    resized = padded.resize(
        (max(8, int(padded.width * scale)), max(8, int(padded.height * scale))),
        Image.Resampling.NEAREST,
    )
    rotated = resized.rotate(
        angle,
        resample=Image.Resampling.BICUBIC,
        expand=True,
        fillcolor=(0, 0, 0, 0),
    )
    if random.random() < 0.45:
        alpha = rotated.getchannel("A").filter(ImageFilter.GaussianBlur(random.uniform(0.25, 0.8)))
        rotated.putalpha(alpha)
    return rotated


def make_noisy_background(width: int, height: int) -> Image.Image:
    base_colors = [
        (74, 22, 28),
        (38, 35, 48),
        (32, 58, 70),
        (83, 65, 34),
        (24, 66, 44),
        (82, 36, 78),
    ]
    bg = np.zeros((height, width, 3), dtype=np.uint8)
    c1 = np.array(random.choice(base_colors), dtype=np.float32)
    c2 = np.array(random.choice(base_colors), dtype=np.float32)
    for y in range(height):
        mix = y / max(height - 1, 1)
        color = c1 * (1 - mix) + c2 * mix
        bg[y, :, :] = np.clip(color + np.random.normal(0, 10, (width, 3)), 0, 255)
    return Image.fromarray(bg)


def add_tile_warp_background(canvas: Image.Image, cols: int, rows: int) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    tile_w = canvas.width / cols
    tile_h = canvas.height / rows
    for row in range(rows):
        for col in range(cols):
            x1 = int(col * tile_w)
            y1 = int(row * tile_h)
            x2 = int((col + 1) * tile_w)
            y2 = int((row + 1) * tile_h)
            if random.random() < 0.55:
                color = (
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(0, 255),
                    random.randint(12, 42),
                )
                draw.rectangle((x1, y1, x2, y2), fill=color)


def add_captcha_noise(canvas: Image.Image) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    for _ in range(random.randint(75, 130)):
        x1 = random.randint(-50, width)
        y1 = random.randint(-50, height)
        x2 = x1 + random.randint(30, 190)
        y2 = y1 + random.randint(-50, 50)
        color = random_line_color()
        draw.line((x1, y1, x2, y2), fill=color, width=random.randint(1, 4))

    for _ in range(random.randint(650, 1100)):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        radius = random.choice([1, 1, 2])
        color = random_line_color(alpha=random.randint(45, 170))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)

    for _ in range(random.randint(8, 18)):
        x1 = random.randint(0, width - 1)
        y1 = random.randint(0, height - 1)
        x2 = x1 + random.randint(25, 120)
        y2 = y1 + random.randint(15, 90)
        draw.rectangle((x1, y1, x2, y2), fill=random_line_color(alpha=random.randint(25, 75)))


def add_cut_tiles_overlay(canvas: Image.Image, cols: int, rows: int) -> None:
    draw = ImageDraw.Draw(canvas, "RGBA")
    width, height = canvas.size
    for col in range(1, cols):
        x = int(width * col / cols + random.randint(-5, 5))
        draw.line((x, 0, x, height), fill=(255, 255, 255, random.randint(36, 95)), width=random.randint(1, 3))
        if random.random() < 0.4:
            draw.line((x + random.randint(-2, 2), 0, x + random.randint(-2, 2), height), fill=(0, 0, 0, 70), width=1)
    for row in range(1, rows):
        y = int(height * row / rows + random.randint(-5, 5))
        draw.line((0, y, width, y), fill=(255, 255, 255, random.randint(30, 85)), width=random.randint(1, 3))
        if random.random() < 0.4:
            draw.line((0, y + random.randint(-2, 2), width, y + random.randint(-2, 2)), fill=(0, 0, 0, 70), width=1)


def add_random_text_fragments(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, width: int, height: int) -> None:
    fragments = ["A", "S", "D", "W", "검증", "입력", "확인", "NOISE", "TILE"]
    for _ in range(random.randint(12, 24)):
        text = random.choice(fragments)
        pos = (random.randint(0, width - 70), random.randint(0, height - 24))
        draw.text(pos, text, fill=random_line_color(alpha=random.randint(40, 120)), font=font)


def final_degrade(canvas: Image.Image) -> Image.Image:
    arr = np.asarray(canvas).astype(np.float32)
    arr += np.random.normal(0, random.uniform(8, 28), arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr)
    out = ImageEnhance.Contrast(out).enhance(random.uniform(0.75, 1.45))
    out = ImageEnhance.Color(out).enhance(random.uniform(0.65, 1.55))
    if random.random() < 0.55:
        out = out.filter(ImageFilter.GaussianBlur(random.uniform(0.15, 0.8)))
    if random.random() < 0.75:
        out = jpeg_roundtrip(out, quality=random.randint(28, 72))
    return out


def jpeg_roundtrip(image: Image.Image, quality: int) -> Image.Image:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


def make_preview(tiles: list[Image.Image]) -> Image.Image:
    font = load_font(22)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    pad = 12
    header = 42
    tile_w, tile_h = tiles[0].size
    canvas = Image.new("RGB", (cols * tile_w + (cols + 1) * pad, rows * tile_h + (rows + 1) * pad + header), (18, 20, 24))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 10), "Captcha-like 800x600 samples preview", fill=(255, 255, 255), font=font)
    for index, tile in enumerate(tiles):
        col = index % cols
        row = index // cols
        x = pad + col * (tile_w + pad)
        y = header + pad + row * (tile_h + pad)
        canvas.paste(tile, (x, y))
    return canvas


def random_line_color(alpha: int | None = None) -> tuple[int, int, int, int]:
    if alpha is None:
        alpha = random.randint(35, 150)
    palette = [
        (255, 255, 255),
        (255, 232, 0),
        (0, 180, 255),
        (255, 80, 150),
        (60, 255, 120),
        (0, 0, 0),
    ]
    return (*random.choice(palette), alpha)


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
    raise SystemExit(main())
