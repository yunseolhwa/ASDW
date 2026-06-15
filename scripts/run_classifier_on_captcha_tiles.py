from __future__ import annotations

import json
import sys
from pathlib import Path

import torch
from PIL import Image, ImageDraw, ImageFont
from transformers import AutoImageProcessor, AutoModelForImageClassification


PROJECT = (
    Path("/mnt/d/asdw-fusion-typer")
    if Path("/mnt/d/asdw-fusion-typer").exists()
    else Path("D:/asdw-fusion-typer")
)
KEYS = ("A", "S", "D", "W")

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import normalize_classifier_crop  # noqa: E402


def main() -> int:
    data_dir = PROJECT / "captcha_tiles_800x600"
    labels = json.loads((data_dir / "labels.json").read_text(encoding="utf-8"))
    model_dir = PROJECT / "models" / "asdw-mobilenetv3-classifier" / "best"

    processor = AutoImageProcessor.from_pretrained(model_dir)
    model = AutoModelForImageClassification.from_pretrained(model_dir).to("cuda").eval()

    correct = 0
    total = 0
    sequence_correct = 0
    rows = []
    annotated = []
    font = load_font(18)
    small = load_font(14)

    with torch.no_grad():
        for row_index, row in enumerate(labels, start=1):
            image = Image.open(data_dir / row["file"]).convert("RGB")
            draw = ImageDraw.Draw(image)
            predictions = []
            confidences = []

            for obj in row["objects"]:
                x1, y1, x2, y2 = obj["bbox_xyxy"]
                x1 = max(0, int(x1))
                y1 = max(0, int(y1))
                x2 = min(image.width, int(x2))
                y2 = min(image.height, int(y2))

                crop = image.crop((x1, y1, x2, y2))
                prepared = normalize_classifier_crop(crop)
                batch = processor(images=[prepared], return_tensors="pt")
                batch = {key: value.to("cuda") for key, value in batch.items()}
                probs = model(**batch).logits.softmax(1)[0].detach().cpu().numpy()
                pred = KEYS[int(probs.argmax())]
                conf = float(probs.max())
                truth = obj["label"]

                predictions.append(pred)
                confidences.append(conf)
                ok = pred == truth
                correct += int(ok)
                total += 1

                color = (60, 255, 120) if ok else (255, 80, 80)
                draw.rectangle((x1, y1, x2, y2), outline=color, width=3)
                draw.text((x1, max(0, y1 - 20)), f"{truth}>{pred} {conf:.2f}", fill=color, font=small)

            pred_sequence = "".join(predictions)
            sequence_ok = pred_sequence == row["sequence"]
            sequence_correct += int(sequence_ok)
            rows.append(
                {
                    "id": row["id"],
                    "file": row["file"],
                    "truth": row["sequence"],
                    "pred": pred_sequence,
                    "ok": sequence_ok,
                    "avg_conf": sum(confidences) / len(confidences),
                }
            )

            if row_index <= 12:
                thumb = image.resize((240, 180), Image.Resampling.LANCZOS)
                thumb_draw = ImageDraw.Draw(thumb)
                thumb_draw.text(
                    (6, 6),
                    f"#{row_index:03d} {'OK' if sequence_ok else 'ERR'}",
                    fill=(255, 255, 0),
                    font=font,
                )
                annotated.append(thumb)

    out_json = PROJECT / "captcha_tiles_800x600_predictions.json"
    out_json.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")

    preview = make_preview(
        annotated,
        f"Classifier on captcha bbox crops: {correct}/{total} buttons, "
        f"{sequence_correct}/{len(labels)} sequences",
    )
    preview_path = PROJECT / "captcha_tiles_800x600_predictions_preview.png"
    preview.save(preview_path)

    print(f"device=cuda gpu={torch.cuda.get_device_name(0)}")
    print(f"button_accuracy={correct}/{total} = {correct / total:.4f}")
    print(f"sequence_accuracy={sequence_correct}/{len(labels)} = {sequence_correct / len(labels):.4f}")
    print("first_20:")
    for row in rows[:20]:
        mark = "OK" if row["ok"] else "ERR"
        print(f"{row['id']:03d} | {row['truth']} | {row['pred']} | {row['avg_conf']:.3f} | {mark}")
    print(f"predictions={out_json}")
    print(f"preview={preview_path}")
    return 0


def make_preview(tiles: list[Image.Image], title: str) -> Image.Image:
    font = load_font(22)
    cols = 3
    rows = (len(tiles) + cols - 1) // cols
    pad = 12
    header = 42
    tile_w, tile_h = tiles[0].size
    canvas = Image.new(
        "RGB",
        (cols * tile_w + (cols + 1) * pad, rows * tile_h + (rows + 1) * pad + header),
        (18, 20, 24),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 10), title, fill=(255, 255, 255), font=font)
    for index, tile in enumerate(tiles):
        x = pad + (index % cols) * (tile_w + pad)
        y = header + pad + (index // cols) * (tile_h + pad)
        canvas.paste(tile, (x, y))
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
