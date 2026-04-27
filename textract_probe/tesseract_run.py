"""Tesseract bake-off runner — raw + (optional) preprocessed pass.

For each fixture: convert TIF -> PNG, run Tesseract twice if --preprocess,
save extracted text + per-word TSV with bboxes + confidences.

Usage:
  python3 -m textract_probe.tesseract_run \\
      --fixtures-file textract_probe/fixtures.json \\
      --out-dir textract_probe/output/tesseract \\
      --preprocess
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from textract_probe.convert import tif_to_png_bytes

SAMPLES = Path("samples")


def _preprocess(png_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(png_bytes)).convert("L")
    img = ImageOps.autocontrast(img)
    threshold = 160
    bw = img.point(lambda p: 0 if p < threshold else 255, mode="1")
    out = io.BytesIO()
    bw.save(out, format="PNG")
    return out.getvalue()


def _run_one(label: str, png: bytes, suffix: str, out_dir: Path) -> tuple[int, float]:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        f.flush()
        path = f.name
    try:
        text = pytesseract.image_to_string(path)
        tsv = pytesseract.image_to_data(path, output_type=pytesseract.Output.STRING)
    finally:
        Path(path).unlink(missing_ok=True)

    (out_dir / f"{label}__tesseract_{suffix}.txt").write_text(text)
    (out_dir / f"{label}__tesseract_{suffix}.tsv").write_text(tsv)

    lines = tsv.splitlines()[1:]
    confs: list[float] = []
    word_count = 0
    for ln in lines:
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        text = parts[-1].strip()
        if not text:
            continue
        word_count += 1
        try:
            c = float(parts[-2])
        except ValueError:
            continue
        if c >= 0:
            confs.append(c)
    avg_conf = (sum(confs) / len(confs)) if confs else 0.0
    return word_count, avg_conf


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument(
        "--preprocess",
        action="store_true",
        help="also run a preprocessed pass (grayscale + autocontrast + threshold)",
    )
    args = p.parse_args(argv)

    fixtures = json.loads(args.fixtures_file.read_text())
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"{'fixture':<35}{'pass':<10}{'words':<8}{'avg_conf':<10}")
    print("-" * 70)
    for fx in fixtures:
        tif = SAMPLES / fx["rel_path"]
        if not tif.exists():
            print(f"SKIP missing: {tif}", file=sys.stderr)
            continue
        png = tif_to_png_bytes(tif)

        wc, conf = _run_one(fx["label"], png, "raw", args.out_dir)
        print(f"{fx['label']:<35}{'raw':<10}{wc:<8}{conf:<10.2f}")

        if args.preprocess:
            pre = _preprocess(png)
            wc2, conf2 = _run_one(fx["label"], pre, "pre", args.out_dir)
            print(f"{fx['label']:<35}{'pre':<10}{wc2:<8}{conf2:<10.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
