"""POC runner.

Usage:
  python -m poc.run_poc --roll-id "ROLL 001" \\
      --input samples/test_input_roll001 \\
      --ground-truth samples/output_pdfs_district1_roll001 \\
      [--limit 20] [--concurrency 8] [--budget-ceiling 10.0]

Outputs under poc/output/ (slug = lower+replace-space-with-underscore of roll-id):
  <slug>_pages.jsonl        one PageResult JSON per line
  <slug>_index.json         deduplicated IndexRow list
  <slug>_students.json      StudentPacket list
  <slug>_spend.jsonl        one Bedrock call per line
  <slug>_eval.json          EvalReport with pre/post snap accuracy
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from poc.classify_extract import classify_page
from poc.eval import evaluate
from poc.group import group_pages
from poc.index import build_roll_index, write_index_json
from poc.schemas import PageResult


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
    ap.add_argument("--budget-ceiling", type=float, default=10.0,
                    help="Hard halt once cumulative Bedrock spend >= this USD. 0 disables.")
    ap.add_argument("--output-dir", default="poc/output")
    args = ap.parse_args()

    in_dir = Path(args.input)
    tifs = sorted(in_dir.glob("*.tif"))
    if args.limit:
        tifs = tifs[: args.limit]
    if not tifs:
        print(f"no .tif in {in_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(args.roll_id)
    pages_path = out_dir / f"{slug}_pages.jsonl"
    index_path = out_dir / f"{slug}_index.json"
    students_path = out_dir / f"{slug}_students.json"
    spend_path = out_dir / f"{slug}_spend.jsonl"
    eval_path = out_dir / f"{slug}_eval.json"

    results: list[PageResult] = []
    spend_lock = threading.Lock()
    cum_usd = 0.0
    halted = False

    print(f"classifying {len(tifs)} tifs @ concurrency {args.concurrency}, "
          f"budget ceiling ${args.budget_ceiling:.2f}")

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex, \
            pages_path.open("w") as pf, \
            spend_path.open("w") as sf:
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

            with spend_lock:
                cum_usd += r.usd_cost
            sf.write(json.dumps({
                "page_id": f"{slug}_{r.frame}",
                "frame": r.frame,
                "roll_id": r.roll_id,
                "purpose": "classify",
                "model_id": r.model_version,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "usd_total": r.usd_cost,
                "latency_ms": r.latency_ms,
                "page_class": r.page_class,
            }) + "\n")

            if i % 25 == 0 or i == len(tifs):
                print(f"  [{i}/{len(tifs)}] last={r.frame} class={r.page_class} "
                      f"conf={r.confidence_overall:.2f} usd=${cum_usd:.4f}")

            if args.budget_ceiling > 0 and cum_usd >= args.budget_ceiling and not halted:
                print(f"BUDGET CEILING ${args.budget_ceiling:.2f} reached "
                      f"(actual ${cum_usd:.4f}). Stopping further submissions.",
                      file=sys.stderr)
                halted = True
                for pending_fut in futs:
                    if not pending_fut.done():
                        pending_fut.cancel()

    if halted:
        print("Halted mid-run due to budget ceiling. Partial results written.", file=sys.stderr)

    # Index stage.
    roll_index = build_roll_index(results)
    write_index_json(roll_index, index_path)
    index_frames = sum(1 for r in results if r.page_class == "student_records_index")
    print(f"index: frames={index_frames} rows={len(roll_index)} -> {index_path}")

    # Grouping (applies H2.7 snap internally).
    packets = group_pages(results, roll_index=roll_index,
                          confidence_threshold=args.confidence_threshold)
    students_path.write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    snapped = sum(1 for p in packets if p.index_snap_applied)
    print(f"packets: total={len(packets)} snapped={snapped} -> {students_path}")

    # Eval.
    gt_files = [p.name for p in Path(args.ground_truth).glob("*.pdf")]
    report = evaluate(packets, gt_files, roll_id=args.roll_id,
                      index_frames_total=index_frames,
                      index_rows_total=len(roll_index))
    report.pages_total = len(tifs)
    report.pages_classified = len(results)
    report.usd_total = cum_usd
    report.tokens_in_total = sum(r.tokens_in for r in results)
    report.tokens_out_total = sum(r.tokens_out for r in results)
    eval_path.write_text(report.model_dump_json(indent=2))

    print(
        f"eval: pre_partial={report.accuracy_partial_pre:.1%} "
        f"post_partial={report.accuracy_partial_post:.1%} "
        f"(exact_pre={report.exact_matches_pre}/{report.packets_predicted}, "
        f"exact_post={report.exact_matches_post}/{report.packets_predicted}) "
        f"spend=${report.usd_total:.4f} -> {eval_path}"
    )
    return 0 if not halted else 2


if __name__ == "__main__":
    raise SystemExit(main())
