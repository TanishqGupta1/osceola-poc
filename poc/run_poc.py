"""
Usage:
  # Process first 20 TIFs for prompt iteration:
  python -m poc.run_poc --roll-id "ROLL 001" \
      --input samples/test_input_roll001 \
      --ground-truth samples/output_pdfs_district1_roll001 \
      --limit 20

  # Full run:
  python -m poc.run_poc --roll-id "ROLL 001" \
      --input samples/test_input_roll001 \
      --ground-truth samples/output_pdfs_district1_roll001

Outputs to poc/output/<roll_slug>_{pages.jsonl,students.json,eval.json}.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import dotenv_values

from poc.classify_extract import classify_page
from poc.eval import evaluate
from poc.group import group_pages
from poc.schemas import PageResult


def _load_env():
    for k, v in dotenv_values(".env").items():
        os.environ.setdefault(k, v)


def _slug(roll_id: str) -> str:
    return roll_id.lower().replace(" ", "_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roll-id", required=True)
    ap.add_argument("--input", required=True, help="dir of TIFs")
    ap.add_argument("--ground-truth", required=True, help="dir of PDFs")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--confidence-threshold", type=float, default=0.7)
    ap.add_argument("--output-dir", default="poc/output")
    args = ap.parse_args()

    _load_env()

    in_dir = Path(args.input)
    tifs = sorted(in_dir.glob("*.tif"))
    if args.limit:
        tifs = tifs[: args.limit]
    if not tifs:
        print(f"no .tif in {in_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.roll_id)
    pages_path = out_dir / f"{slug}_pages.jsonl"
    students_path = out_dir / f"{slug}_students.json"
    eval_path = out_dir / f"{slug}_eval.json"

    results: list[PageResult] = []
    print(f"classifying {len(tifs)} tifs @ concurrency {args.concurrency}")
    with ThreadPoolExecutor(max_workers=args.concurrency) as ex, pages_path.open("w") as pf:
        futs = {ex.submit(classify_page, t, args.roll_id): t for t in tifs}
        for i, fut in enumerate(as_completed(futs), 1):
            tif = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                print(f"  [{i}/{len(tifs)}] {tif.name}: ERROR {e!r}", file=sys.stderr)
                continue
            results.append(r)
            pf.write(r.model_dump_json() + "\n")
            if i % 25 == 0 or i == len(tifs):
                print(f"  [{i}/{len(tifs)}] last={r.frame} class={r.page_class} conf={r.confidence_overall:.2f}")

    packets = group_pages(results, confidence_threshold=args.confidence_threshold)
    students_path.write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    print(f"wrote {len(packets)} packets → {students_path}")

    gt_files = [p.name for p in Path(args.ground_truth).glob("*.pdf")]
    report = evaluate(packets, gt_files, roll_id=args.roll_id)
    report.pages_total = len(tifs)
    report.pages_classified = len(results)
    eval_path.write_text(report.model_dump_json(indent=2))
    print(f"eval: exact={report.accuracy_exact:.1%} partial={report.accuracy_partial:.1%} "
          f"({report.exact_name_matches}/{report.packets_predicted} exact) → {eval_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
