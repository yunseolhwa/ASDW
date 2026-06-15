from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


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
RANDOM_SEED = 20260616

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import find_button_boxes  # noqa: E402


def main() -> int:
    random.seed(RANDOM_SEED)
    image = Image.open(SOURCE).convert("RGB")
    roi = crop_roi(image)
    boxes = find_button_boxes(roi)
    crops = [(label, roi.crop(box)) for label, box in zip(ORIGINAL_SEQUENCE, boxes, strict=True)]

    rows = []
    used_sequences: set[str] = set()
    for row_index in range(18):
        shuffled = crops[:]
        random.shuffle(shuffled)
        sequence = "".join(label for label, _ in shuffled)
        while sequence in used_sequences:
            random.shuffle(shuffled)
            sequence = "".join(label for label, _ in shuffled)
        used_sequences.add(sequence)
        rows.append(render_sequence_row(shuffled, row_index + 1, sequence))

    output = make_grid(rows, columns=2)
    output_path = PROJECT / "shuffled-original-sequences.png"
    output.save(output_path)

    sequences_path = PROJECT / "shuffled-original-sequences.txt"
    sequences_path.write_text("\n".join(used_sequences), encoding="utf-8")

    print(output_path)
    print(sequences_path)

    scaled_rows = []
    random.seed(RANDOM_SEED)
    for row_index in range(18):
        shuffled = crops[:]
        random.shuffle(shuffled)
        sequence = "".join(label for label, _ in shuffled)
        scaled_rows.append(render_scaled_sequence_row(shuffled, row_index + 1, sequence))

    scaled_output = make_grid(scaled_rows, columns=2)
    scaled_path = PROJECT / "shuffled-original-random-scale-50.png"
    scaled_output.save(scaled_path)
    print(scaled_path)
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


def render_sequence_row(
    shuffled: list[tuple[str, Image.Image]],
    row_index: int,
    sequence: str,
) -> Image.Image:
    font = load_font(18)
    small = load_font(14)
    pad = 8
    gap = 4
    scale = 1
    crop_w = max(crop.width for _, crop in shuffled) * scale
    crop_h = max(crop.height for _, crop in shuffled) * scale
    label_w = 132
    width = label_w + pad + len(shuffled) * crop_w + (len(shuffled) - 1) * gap + pad
    height = crop_h + pad * 2
    canvas = Image.new("RGB", (width, height), (28, 24, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 9), f"#{row_index:02d}", fill=(255, 232, 0), font=font)
    draw.text((pad, 34), sequence, fill=(255, 255, 255), font=small)
    x = label_w
    for label, crop in shuffled:
        tile = Image.new("RGB", (crop_w, crop_h), (40, 28, 34))
        tile.paste(crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST), (0, 0))
        canvas.paste(tile, (x, pad))
        draw.rectangle((x, pad, x + crop_w - 1, pad + crop_h - 1), outline=(255, 232, 0), width=2)
        draw.text((x + 3, pad + 2), label, fill=(255, 232, 0), font=small)
        x += crop_w + gap
    return canvas


def render_scaled_sequence_row(
    shuffled: list[tuple[str, Image.Image]],
    row_index: int,
    sequence: str,
) -> Image.Image:
    font = load_font(18)
    small = load_font(14)
    pad = 8
    gap = 5
    label_w = 132
    slot_w = 82
    slot_h = 82
    width = label_w + pad + len(shuffled) * slot_w + (len(shuffled) - 1) * gap + pad
    height = slot_h + pad * 2
    canvas = Image.new("RGB", (width, height), (28, 24, 28))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 9), f"#{row_index:02d}", fill=(255, 232, 0), font=font)
    draw.text((pad, 34), sequence, fill=(255, 255, 255), font=small)
    x = label_w
    for label, crop in shuffled:
        scale = random.uniform(0.50, 1.50)
        new_w = max(8, int(crop.width * scale))
        new_h = max(8, int(crop.height * scale))
        resized = crop.resize((new_w, new_h), Image.Resampling.NEAREST)
        tile = Image.new("RGB", (slot_w, slot_h), (40, 28, 34))
        paste_x = (slot_w - resized.width) // 2
        paste_y = (slot_h - resized.height) // 2
        tile.paste(resized, (paste_x, paste_y))
        canvas.paste(tile, (x, pad))
        draw.rectangle((x, pad, x + slot_w - 1, pad + slot_h - 1), outline=(255, 232, 0), width=2)
        draw.text((x + 3, pad + 2), f"{label} {scale:.2f}x", fill=(255, 232, 0), font=small)
        x += slot_w + gap
    return canvas


def make_grid(rows: list[Image.Image], columns: int) -> Image.Image:
    font = load_font(24)
    pad = 16
    header = 46
    cell_w = max(row.width for row in rows)
    cell_h = max(row.height for row in rows)
    grid_rows = (len(rows) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (columns * cell_w + (columns + 1) * pad, grid_rows * cell_h + (grid_rows + 1) * pad + header),
        (18, 20, 24),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (pad, 12),
        "Original crops cloned and randomly reordered",
        fill=(255, 255, 255),
        font=font,
    )
    for index, row in enumerate(rows):
        col = index % columns
        grid_row = index // columns
        x = pad + col * (cell_w + pad)
        y = header + pad + grid_row * (cell_h + pad)
        canvas.paste(row, (x, y))
    return canvas


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
