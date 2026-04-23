"""Re-run grouping + eval from an existing pages.jsonl — no Bedrock calls.

Usage:
  python -m poc.regroup --roll-id "ROLL 001" \
      --ground-truth samples/output_pdfs_district1_roll001_full \
      [--no-merge]
"""
import argparse
import json
import sys
from pathlib import Path

from poc.eval import evaluate
from poc.group import group_pages
from poc.index import build_roll_index, write_index_json
from poc.schemas import PageResult


def _slug(roll_id: str) -> str:
    return roll_id.lower().replace(" ", "_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roll-id", required=True)
    ap.add_argument("--ground-truth", required=True)
    ap.add_argument("--output-dir", default="poc/output")
    ap.add_argument("--no-merge", action="store_true",
                    help="Disable H2.4 adjacent-packet merge for comparison runs.")
    ap.add_argument("--mode", choices=["boundary", "index"], default="boundary",
                    help="boundary = name-change grouping; index = cluster by snap target.")
    ap.add_argument("--confidence-threshold", type=float, default=0.7)
    args = ap.parse_args()

    slug = _slug(args.roll_id)
    out = Path(args.output_dir)
    pages_path = out / f"{slug}_pages.jsonl"
    if not pages_path.exists():
        print(f"missing {pages_path}", file=sys.stderr)
        return 2

    pages = [PageResult.model_validate_json(line) for line in pages_path.read_text().splitlines() if line]
    print(f"loaded {len(pages)} pages from {pages_path}")

    roll_index = build_roll_index(pages)
    write_index_json(roll_index, out / f"{slug}_index.json")
    index_frames = sum(1 for r in pages if r.page_class == "student_records_index")
    print(f"index: frames={index_frames} rows={len(roll_index)}")

    if args.mode == "index":
        from poc.group import group_by_index_entry
        packets = group_by_index_entry(
            pages,
            roll_index=roll_index,
            confidence_threshold=args.confidence_threshold,
        )
    else:
        packets = group_pages(
            pages,
            roll_index=roll_index,
            confidence_threshold=args.confidence_threshold,
            enable_merge=not args.no_merge,
        )
    (out / f"{slug}_students.json").write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    snapped = sum(1 for p in packets if p.index_snap_applied)
    print(f"packets: total={len(packets)} snapped={snapped}")

    gt_files = [p.name for p in Path(args.ground_truth).glob("*.pdf")]
    report = evaluate(packets, gt_files, roll_id=args.roll_id,
                      index_frames_total=index_frames,
                      index_rows_total=len(roll_index))
    report.pages_total = len(pages)
    report.pages_classified = len(pages)
    report.usd_total = sum(p.usd_cost for p in pages)
    report.tokens_in_total = sum(p.tokens_in for p in pages)
    report.tokens_out_total = sum(p.tokens_out for p in pages)
    eval_path = out / f"{slug}_eval.json"
    eval_path.write_text(report.model_dump_json(indent=2))

    print(
        f"eval: pre_partial={report.accuracy_partial_pre:.1%} "
        f"post_partial={report.accuracy_partial_post:.1%} "
        f"exact_pre={report.exact_matches_pre}/{report.packets_predicted} "
        f"exact_post={report.exact_matches_post}/{report.packets_predicted} "
        f"gt_usable={report.gt_rows_usable}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
