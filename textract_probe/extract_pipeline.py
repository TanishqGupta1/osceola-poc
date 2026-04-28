"""End-to-end V4 extractor — drives the full pure-code-logic pipeline.

For each fixture:
  1. Router decides page_class + which Textract calls to make.
  2. If `student_records_index`: parse Tables -> add IndexRows.
  3. If `student_cover`: extract candidates from Forms NAME, Forms-empty-VALUE
     bbox fallback, Queries v2 RECORD_NAME/TOP_NAME/FULL_NAME, Detect first
     non-label LINE; vote; if vote returned only `last`, snap to roll index.
  4. Emit per-page result row.

Writes:
  textract_probe/output/v4/<run_label>_results.jsonl
  textract_probe/output/v4/<run_label>_summary.txt

Usage:
  python3 -m textract_probe.extract_pipeline \
      --fixtures-file textract_probe/fixtures_round3.json \
      --queries-file textract_probe/queries_v2.json \
      --run-label round3_v4 \
      --budget-ceiling 2.00
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from textract_probe import bbox_extract, name_voter, validators
from textract_probe.convert import tif_to_png_bytes
from textract_probe.index_snap import (
    IndexRow,
    parse_tables_into_index_rows,
    snap_packet_name_to_index,
)
from textract_probe.router import process_page

SAMPLES = Path("samples")
OUT = Path("textract_probe/output/v4")


def _by_id(blocks):
    return {b["Id"]: b for b in blocks if "Id" in b}


def _text_of(block, by_id):
    out = []
    for rel in block.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                c = by_id.get(cid)
                if c and c.get("BlockType") == "WORD":
                    out.append((c.get("Text") or "").strip())
    return " ".join(out).strip()


def _query_answer(resp, alias):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    for q in [b for b in blocks if b.get("BlockType") == "QUERY"]:
        if (q.get("Query") or {}).get("Alias") != alias:
            continue
        for rel in q.get("Relationships", []) or []:
            if rel.get("Type") == "ANSWER":
                for rid in rel.get("Ids", []):
                    a = by_id.get(rid)
                    if a:
                        return (a.get("Text") or "", a.get("Confidence", 0.0))
    return ("", 0.0)


def _forms_name_value(resp):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    keys = [
        b for b in blocks
        if b.get("BlockType") == "KEY_VALUE_SET"
        and "KEY" in (b.get("EntityTypes") or [])
    ]
    best = ("", 0.0)
    for k in keys:
        ktext = _text_of(k, by_id).upper()
        if "NAME" in ktext and "MOTHER" not in ktext and "FATHER" not in ktext \
                and "PARENT" not in ktext and "GUARDIAN" not in ktext:
            val = ""
            for rel in k.get("Relationships", []) or []:
                if rel.get("Type") == "VALUE":
                    for vid in rel.get("Ids", []):
                        v = by_id.get(vid)
                        if v:
                            val = _text_of(v, by_id)
            conf = k.get("Confidence", 0.0)
            if val and conf > best[1]:
                best = (val, conf)
    return best


def _forms_empty_label_bbox_fallback(resp, label="LAST"):
    if not resp:
        return ("", 0.0)
    blocks = resp.get("Blocks", []) or []
    val = bbox_extract.extract_value_near_anchor(
        blocks, anchor_text=label, direction="right"
    )
    return (val, 50.0 if val else 0.0)


def _detect_first_non_label_line(detect_resp):
    blocks = detect_resp.get("Blocks", []) or []
    for b in blocks:
        if b.get("BlockType") != "LINE":
            continue
        text = (b.get("Text") or "").strip()
        if not text:
            continue
        if validators.is_valid_student_name(text):
            return (text, b.get("Confidence", 0.0))
    return ("", 0.0)


def _process_one(
    fixture: dict,
    queries: list[dict] | None,
    roll_index_acc: list[IndexRow],
) -> dict[str, Any]:
    rel = fixture["rel_path"]
    label = fixture["label"]
    tif = SAMPLES / rel
    if not tif.exists():
        return {"label": label, "error": f"missing fixture: {tif}"}
    png = tif_to_png_bytes(tif)
    routed = process_page(png, queries=queries)

    pass2 = routed.get("pass2_response")
    detect = routed["detect_response"]
    page_class = routed["page_class"]
    spend = routed["spend_usd"]

    out: dict[str, Any] = {
        "label": label,
        "rel_path": rel,
        "expected_class": fixture.get("expected_class"),
        "expected_name": fixture.get("expected_name"),
        "page_class": page_class,
        "classifier_confidence": routed["classifier_confidence"],
        "spend_usd": spend,
    }

    if page_class == "student_records_index":
        rows = parse_tables_into_index_rows(pass2 or detect)
        roll_index_acc.extend(rows)
        out["index_rows_added"] = len(rows)
        return out

    if page_class != "student_cover":
        return out

    forms_name, forms_conf       = _forms_name_value(pass2)
    forms_bbox, forms_bbox_conf  = _forms_empty_label_bbox_fallback(pass2, "LAST")
    q_record, q_record_conf      = _query_answer(pass2, "RECORD_NAME")
    q_top,    q_top_conf         = _query_answer(pass2, "TOP_NAME")
    q_full,   q_full_conf        = _query_answer(pass2, "FULL_NAME")
    detect_first, detect_conf    = _detect_first_non_label_line(detect)

    sources = [
        ("forms_name",     forms_name,    forms_conf),
        ("forms_bbox",     forms_bbox,    forms_bbox_conf),
        ("queries_record", q_record,      q_record_conf),
        ("queries_top",    q_top,         q_top_conf),
        ("queries_full",   q_full,        q_full_conf),
        ("detect_first",   detect_first,  detect_conf),
    ]

    vote = name_voter.vote_on_name(sources)

    snapped = None
    if vote.name and " " not in vote.name and roll_index_acc:
        snapped = snap_packet_name_to_index(
            last_raw=vote.name, first_raw="", middle_raw="", index=roll_index_acc,
        )

    out["candidate_sources"] = [
        {"source": s, "raw": r, "conf": c} for (s, r, c) in sources
    ]
    out["vote_name"] = vote.name
    out["vote_confidence"] = vote.confidence
    out["vote_agreement"] = vote.agreement
    out["vote_sources"] = vote.sources
    out["snapped"] = (
        {"last": snapped.last, "first": snapped.first,
         "middle": snapped.middle, "dob": snapped.dob}
        if snapped else None
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--queries-file", type=Path, default=Path("textract_probe/queries_v2.json"))
    p.add_argument("--run-label", required=True, type=str)
    p.add_argument("--budget-ceiling", type=float, default=2.00)
    args = p.parse_args(argv)

    fixtures = json.loads(args.fixtures_file.read_text())
    queries  = json.loads(args.queries_file.read_text()) if args.queries_file.exists() else None

    OUT.mkdir(parents=True, exist_ok=True)
    results_jsonl = OUT / f"{args.run_label}_results.jsonl"
    summary_txt   = OUT / f"{args.run_label}_summary.txt"

    spend = 0.0
    rows = []
    roll_index_acc: list[IndexRow] = []

    with results_jsonl.open("w", buffering=1) as f:
        for fx in fixtures:
            if spend >= args.budget_ceiling:
                print(
                    f"HALT: budget ${args.budget_ceiling} reached (${spend:.4f})",
                    file=sys.stderr,
                )
                break
            r = _process_one(fx, queries, roll_index_acc)
            spend += r.get("spend_usd", 0.0)
            f.write(json.dumps(r, default=str) + "\n")
            f.flush()
            rows.append(r)
            print(
                f"OK {r['label']:<35} class={r.get('page_class','?'):<22} "
                f"name={(r.get('vote_name') or '-')[:30]:<30} "
                f"agree={r.get('vote_agreement','-')} "
                f"conf={r.get('vote_confidence','-')} ${r['spend_usd']:.4f} "
                f"total=${spend:.4f}"
            )

    n_total = len(rows)
    n_correct = 0
    n_shipped = 0
    for r in rows:
        if r.get("expected_name") and r.get("vote_name"):
            exp = r["expected_name"].lower().strip()
            got = r["vote_name"].lower().strip()
            if got and (got in exp or exp in got):
                n_correct += 1
            if r.get("vote_confidence", 0) >= 0.60:
                n_shipped += 1

    summary = (
        f"V4 run: {args.run_label}\n"
        f"Fixtures processed: {n_total}\n"
        f"Total spend: ${spend:.4f}\n"
        f"Vote names matching expected (substring): {n_correct}\n"
        f"Pages eligible to ship (vote_confidence >= 0.60): {n_shipped}\n"
        f"Roll index accumulated rows: {len(roll_index_acc)}\n"
    )
    summary_txt.write_text(summary)
    print()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
