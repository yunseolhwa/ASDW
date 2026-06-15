from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont
from torch.utils.data import DataLoader, Dataset
from transformers import AutoImageProcessor, AutoModelForImageClassification


PROJECT = (
    Path("/mnt/d/asdw-fusion-typer")
    if Path("/mnt/d/asdw-fusion-typer").exists()
    else Path("D:/asdw-fusion-typer")
)
KEYS = ("A", "S", "D", "W")

sys.path.insert(0, str(PROJECT))

from asdw_fusion.server import find_button_boxes  # noqa: E402


@dataclass
class Sample:
    path: Path
    label: int


class AsdwDataset(Dataset):
    def __init__(self, root: Path, split: str) -> None:
        self.samples: list[Sample] = []
        for label_id, key in enumerate(KEYS):
            class_dir = root / split / key
            for path in sorted(class_dir.glob("*.png")):
                self.samples.append(Sample(path=path, label=label_id))
        if not self.samples:
            raise RuntimeError(f"No samples found in {root / split}")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int) -> tuple[Image.Image, int]:
        sample = self.samples[index]
        return Image.open(sample.path).convert("RGB"), sample.label


def main() -> int:
    parser = argparse.ArgumentParser(description="Fine-tune HF image classifier for ASDW keys.")
    parser.add_argument("--data-root", type=Path, default=PROJECT / "data" / "asdw_classifier")
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "models" / "asdw-mobilenetv3-classifier")
    parser.add_argument("--model-id", default="timm/mobilenetv3_small_100.lamb_in1k")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--lr", type=float, default=8e-5)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=20260616)
    parser.add_argument("--num-workers", type=int, default=2)
    parser.add_argument("--freeze-backbone", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    os.environ.setdefault("HSA_ENABLE_SDMA", "0")
    os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "10.3.0")
    seed_everything(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        raise RuntimeError("ROCm GPU is not available through torch.cuda")

    train_data = AsdwDataset(args.data_root, "train")
    val_data = AsdwDataset(args.data_root, "val")

    id2label = {index: key for index, key in enumerate(KEYS)}
    label2id = {key: index for index, key in id2label.items()}
    processor = AutoImageProcessor.from_pretrained(args.model_id)
    model = AutoModelForImageClassification.from_pretrained(
        args.model_id,
        num_labels=len(KEYS),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )

    if args.freeze_backbone:
        freeze_for_transfer_learning(model)

    model.to(device)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"device={device} gpu={torch.cuda.get_device_name(0)}")
    print(f"trainable_params={trainable} total_params={total}")

    train_loader = DataLoader(
        train_data,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        collate_fn=lambda batch: collate(batch, processor),
        pin_memory=False,
    )
    val_loader = DataLoader(
        val_data,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        collate_fn=lambda batch: collate(batch, processor),
        pin_memory=False,
    )

    optimizer = torch.optim.AdamW(
        [param for param in model.parameters() if param.requires_grad],
        lr=args.lr,
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    best_dir = args.output_dir / "best"
    best_acc = -1.0
    history = []
    started = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, optimizer, device)
        val_loss, val_acc, confusion = evaluate(model, val_loader, device)
        scheduler.step()
        row = {
            "epoch": epoch,
            "train_loss": round(train_loss, 5),
            "train_acc": round(train_acc, 5),
            "val_loss": round(val_loss, 5),
            "val_acc": round(val_acc, 5),
            "lr": optimizer.param_groups[0]["lr"],
        }
        history.append(row)
        print(json.dumps(row, ensure_ascii=False))
        if val_acc > best_acc:
            best_acc = val_acc
            model.save_pretrained(best_dir)
            processor.save_pretrained(best_dir)
            save_metadata(best_dir, args, history, confusion, best_acc, trainable, total, device)

    elapsed = time.perf_counter() - started
    metrics = {
        "best_val_acc": best_acc,
        "elapsed_sec": round(elapsed, 2),
        "history": history,
    }
    (args.output_dir / "training_metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    draw_original_roi_predictions(best_dir, processor, device, args.output_dir / "original-roi-predictions.png")
    print(f"best_model={best_dir}")
    print(f"best_val_acc={best_acc:.4f}")
    return 0


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def freeze_for_transfer_learning(model: torch.nn.Module) -> None:
    for _, param in model.named_parameters():
        param.requires_grad = False
    trainable_keywords = ("classifier", "head", "fc")
    matched = 0
    for name, param in model.named_parameters():
        if any(keyword in name.lower() for keyword in trainable_keywords):
            param.requires_grad = True
            matched += param.numel()
    if matched == 0:
        for _, param in model.named_parameters():
            param.requires_grad = True


def collate(batch: list[tuple[Image.Image, int]], processor) -> dict[str, torch.Tensor]:
    images, labels = zip(*batch, strict=True)
    encoded = processor(images=list(images), return_tensors="pt")
    encoded["labels"] = torch.tensor(labels, dtype=torch.long)
    return encoded


def train_one_epoch(
    model: torch.nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
    model.train()
    total_loss = 0.0
    correct = 0
    total = 0
    for batch in loader:
        batch = move_batch(batch, device)
        optimizer.zero_grad(set_to_none=True)
        output = model(**batch)
        loss = output.loss
        loss.backward()
        optimizer.step()
        total_loss += float(loss.detach().cpu()) * batch["labels"].shape[0]
        pred = output.logits.argmax(dim=1)
        correct += int((pred == batch["labels"]).sum().detach().cpu())
        total += batch["labels"].shape[0]
    return total_loss / max(total, 1), correct / max(total, 1)


@torch.no_grad()
def evaluate(
    model: torch.nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, float, list[list[int]]]:
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    confusion = np.zeros((len(KEYS), len(KEYS)), dtype=np.int64)
    for batch in loader:
        batch = move_batch(batch, device)
        output = model(**batch)
        total_loss += float(output.loss.detach().cpu()) * batch["labels"].shape[0]
        pred = output.logits.argmax(dim=1)
        labels = batch["labels"]
        correct += int((pred == labels).sum().detach().cpu())
        total += labels.shape[0]
        for truth, guess in zip(labels.detach().cpu().numpy(), pred.detach().cpu().numpy(), strict=False):
            confusion[int(truth), int(guess)] += 1
    return total_loss / max(total, 1), correct / max(total, 1), confusion.tolist()


def move_batch(batch: dict[str, torch.Tensor], device: torch.device) -> dict[str, torch.Tensor]:
    return {key: value.to(device, non_blocking=True) for key, value in batch.items()}


def save_metadata(
    output_dir: Path,
    args: argparse.Namespace,
    history: list[dict],
    confusion: list[list[int]],
    best_acc: float,
    trainable: int,
    total: int,
    device: torch.device,
) -> None:
    payload = {
        "model_id": args.model_id,
        "labels": list(KEYS),
        "best_val_acc": best_acc,
        "confusion_rows_true_cols_pred": confusion,
        "transfer_learning": {
            "freeze_backbone": args.freeze_backbone,
            "trainable_params": trainable,
            "total_params": total,
        },
        "device": str(device),
        "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else "cpu",
        "history": history,
    }
    (output_dir / "asdw_training_metadata.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


@torch.no_grad()
def draw_original_roi_predictions(
    model_dir: Path,
    processor,
    device: torch.device,
    output_path: Path,
) -> None:
    source = (
        Path("/mnt/c/Users/ROCmAdmin/AppData/Local/Temp/codex-clipboard-e3946a09-fd69-4065-a92f-0ab5ef4aa79e.png")
        if Path("/mnt/c/Users/ROCmAdmin/AppData/Local/Temp").exists()
        else Path("C:/Users/ROCmAdmin/AppData/Local/Temp/codex-clipboard-e3946a09-fd69-4065-a92f-0ab5ef4aa79e.png")
    )
    image = Image.open(source).convert("RGB")
    width, height = image.size
    roi = image.crop((int(width * 0.34), int(height * 0.46), int(width * 0.66), int(height * 0.57)))
    boxes = find_button_boxes(roi)
    model = AutoModelForImageClassification.from_pretrained(model_dir).to(device)
    model.eval()

    draw = ImageDraw.Draw(roi)
    font = load_font(18)
    predictions = []
    for index, box in enumerate(boxes, start=1):
        crop = normalize_classifier_crop(roi.crop(box))
        batch = processor(images=[crop], return_tensors="pt")
        batch = {key: value.to(device) for key, value in batch.items()}
        output = model(**batch)
        probs = output.logits.softmax(dim=1)[0].detach().cpu().numpy()
        label_id = int(probs.argmax())
        label = KEYS[label_id]
        conf = float(probs[label_id])
        predictions.append(label)
        draw.rectangle(box, outline=(255, 232, 0), width=3)
        draw.text((box[0] + 2, max(0, box[1] - 20)), f"{index}:{label} {conf:.2f}", fill=(255, 232, 0), font=font)

    scale = 2
    canvas = roi.resize((roi.width * scale, roi.height * scale), Image.Resampling.NEAREST)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    (output_path.parent / "original-roi-predictions.txt").write_text(
        "".join(predictions),
        encoding="utf-8",
    )


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


def normalize_classifier_crop(image: Image.Image, size: int = 112) -> Image.Image:
    side = max(image.size)
    canvas = Image.new("RGB", (side, side), (32, 24, 28))
    canvas.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    return canvas.resize((size, size), Image.Resampling.BICUBIC)


if __name__ == "__main__":
    raise SystemExit(main())
