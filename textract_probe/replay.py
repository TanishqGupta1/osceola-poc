"""V4 replay mode — runs extraction logic against existing per-feature JSONs.

No live Textract calls. Reads raw responses from textract_probe/output/textract/
(forms.json + tables.json + layout.json + queries.json + detect.json per
fixture), merges Blocks into a single pseudo-combined response, then drives
extraction (forms NAME + bbox fallback + queries v2 + voter + index-snap).

Usage:
  python3 -m textract_probe.replay \
      --fixtures-file textract_probe/fixtures_round3.json \
      --responses-dir textract_probe/output/textract \
      --run-label round3_v4_replay
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from textract_probe import bbox_extract, name_voter, validators
from textract_probe.index_snap import (
    IndexRow,
    parse_tables_into_index_rows,
    snap_packet_name_to_index,
)

SAMPLES = Path("samples")
OUT = Path("textract_probe/output/v4")

FEATURE_FILES = ("detect", "forms", "tables", "layout", "queries")


def _load_merged(label: str, responses_dir: Path) -> dict[str, Any]:
    """Merge per-feature JSON Blocks into a single response dict."""
    blocks: list[dict] = []
    found_features: list[str] = []
    for feat in FEATURE_FILES:
        p = responses_dir / f"{label}__{feat}.json"
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        blocks.extend(data.get("Blocks", []) or [])
        found_features.append(feat)
    return {"Blocks": blocks, "_features_loaded": found_features}


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


def _forms_bbox_fallback(resp, label="LAST"):
    blocks = resp.get("Blocks", []) or []
    val = bbox_extract.extract_value_near_anchor(
        blocks, anchor_text=label, direction="right"
    )
    return (val, 50.0 if val else 0.0)


def _detect_first_non_label_line(resp):
    blocks = resp.get("Blocks", []) or []
    for b in blocks:
        if b.get("BlockType") != "LINE":
            continue
        text = (b.get("Text") or "").strip()
        if not text:
            continue
        if validators.is_valid_student_name(text):
            return (text, b.get("Confidence", 0.0))
    return ("", 0.0)


def _process(fixture: dict, responses_dir: Path, roll_index_acc: list[IndexRow]) -> dict:
    label = fixture["label"]
    merged = _load_merged(label, responses_dir)
    expected_class = fixture.get("expected_class")
    out: dict[str, Any] = {
        "label": label,
        "expected_class": expected_class,
        "expected_name": fixture.get("expected_name"),
        "features_loaded": merged["_features_loaded"],
    }

    if expected_class == "student_records_index":
        rows = parse_tables_into_index_rows(merged)
        roll_index_acc.extend(rows)
        out["index_rows_added"] = len(rows)
        return out

    if expected_class != "student_cover":
        return out

    forms_name, forms_conf       = _forms_name_value(merged)
    forms_bbox, forms_bbox_conf  = _forms_bbox_fallback(merged, "LAST")
    q_record, q_record_conf      = _query_answer(merged, "RECORD_NAME")
    q_top,    q_top_conf         = _query_answer(merged, "TOP_NAME")
    q_full,   q_full_conf        = _query_answer(merged, "FULL_NAME")
    detect_first, detect_conf    = _detect_first_non_label_line(merged)

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
    p.add_argument(
        "--responses-dir", type=Path, default=Path("textract_probe/output/textract")
    )
    p.add_argument("--run-label", required=True, type=str)
    args = p.parse_args(argv)

    fixtures = json.loads(args.fixtures_file.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    results_jsonl = OUT / f"{args.run_label}_results.jsonl"
    summary_txt   = OUT / f"{args.run_label}_summary.txt"

    rows = []
    roll_index_acc: list[IndexRow] = []

    with results_jsonl.open("w") as f:
        for fx in fixtures:
            r = _process(fx, args.responses_dir, roll_index_acc)
            f.write(json.dumps(r, default=str) + "\n")
            rows.append(r)
            if "vote_name" in r:
                print(
                    f"  {r['label']:<35} "
                    f"name={(r.get('vote_name') or '-')[:32]:<32} "
                    f"agree={r.get('vote_agreement', '-')} "
                    f"conf={r.get('vote_confidence', '-')} "
                    f"snap={'Y' if r.get('snapped') else 'N'}"
                )
            else:
                print(f"  {r['label']:<35} {r.get('expected_class','?')}")

    n_total = sum(1 for r in rows if r.get("expected_class") == "student_cover")
    n_correct = 0
    n_shipped = 0
    n_shipped_correct = 0
    for r in rows:
        if r.get("expected_class") != "student_cover":
            continue
        exp = (r.get("expected_name") or "").lower().strip()
        got = (r.get("vote_name") or "").lower().strip()
        # Strip common middle-initial / honorific prefixes from `got` for substring match.
        import re as _re
        got_stripped = _re.sub(r"^(?:[a-z]\.\s+|w\.\s+|mr\.\s+|mrs\.\s+)", "", got)
        is_correct = bool(
            got and exp and (
                got in exp or exp in got
                or got_stripped in exp or exp in got_stripped
            )
        )
        if is_correct:
            n_correct += 1
        if r.get("vote_confidence", 0) >= 0.70:
            n_shipped += 1
            if is_correct:
                n_shipped_correct += 1

    precision_pct = (100.0 * n_shipped_correct / n_shipped) if n_shipped else 0.0
    recall_pct = (100.0 * n_correct / n_total) if n_total else 0.0

    summary = (
        f"V4 REPLAY run: {args.run_label}\n"
        f"Fixtures total: {len(rows)} (covers={n_total})\n"
        f"Vote names matching expected: {n_correct} / {n_total} (raw recall {recall_pct:.1f}%)\n"
        f"Shipped at conf >= 0.70 (agreement >= 2): {n_shipped} (precision {precision_pct:.1f}%)\n"
        f"Roll index rows accumulated: {len(roll_index_acc)}\n"
    )
    summary_txt.write_text(summary)
    print()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
