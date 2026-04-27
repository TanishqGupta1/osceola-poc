"""Decode raw Textract response JSONs into human-readable per-fixture digests.

Reads --in-dir for files matching `<label>__<feature>.json`, groups by label,
emits a single markdown file per label to --out-dir, plus an index.md.

Usage:
  python3 -m textract_probe.decode \\
      --in-dir textract_probe/output/textract \\
      --out-dir textract_probe/output/digests
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

FEATURE_ORDER = ["detect", "forms", "tables", "layout", "queries"]


def _by_id(blocks: list[dict]) -> dict[str, dict]:
    return {b["Id"]: b for b in blocks}


def _text_of(block: dict, by_id: dict[str, dict]) -> str:
    out: list[str] = []
    for rel in block.get("Relationships", []) or []:
        if rel["Type"] == "CHILD":
            for cid in rel["Ids"]:
                child = by_id.get(cid)
                if child and child.get("BlockType") == "WORD":
                    out.append(child.get("Text", ""))
    return " ".join(out)


def _digest_detect(resp: dict) -> str:
    blocks = resp.get("Blocks", []) or []
    lines = [b.get("Text", "") for b in blocks if b.get("BlockType") == "LINE"]
    body = ["### Detect", f"- LINEs: **{len(lines)}**", "", "```"]
    for ln in lines[:50]:
        body.append(ln)
    if len(lines) > 50:
        body.append(f"... ({len(lines) - 50} more LINEs)")
    body.append("```")
    return "\n".join(body)


def _digest_forms(resp: dict) -> str:
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    keys = [
        b for b in blocks
        if b.get("BlockType") == "KEY_VALUE_SET"
        and "KEY" in (b.get("EntityTypes") or [])
    ]
    body = ["### Forms (KEY_VALUE_SET)", f"- Key blocks: **{len(keys)}**", "",
            "| conf | key | value |", "|---|---|---|"]
    for k in keys:
        key_text = _text_of(k, by_id)
        val_text = ""
        for rel in k.get("Relationships", []) or []:
            if rel["Type"] == "VALUE":
                for vid in rel["Ids"]:
                    val = by_id.get(vid)
                    if val:
                        val_text = _text_of(val, by_id)
        conf = k.get("Confidence", 0)
        body.append(f"| {conf:.1f} | `{key_text}` | `{val_text}` |")
    return "\n".join(body)


def _digest_tables(resp: dict) -> str:
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    tables = [b for b in blocks if b.get("BlockType") == "TABLE"]
    body = ["### Tables", f"- Tables: **{len(tables)}**"]
    for ti, t in enumerate(tables, start=1):
        cells = []
        for rel in t.get("Relationships", []) or []:
            if rel["Type"] == "CHILD":
                for cid in rel["Ids"]:
                    c = by_id.get(cid)
                    if c and c.get("BlockType") == "CELL":
                        cells.append(c)
        if not cells:
            body.append(f"\n#### Table {ti}: (empty)")
            continue
        rows = max(c.get("RowIndex", 0) for c in cells)
        cols = max(c.get("ColumnIndex", 0) for c in cells)
        grid: dict[tuple[int, int], str] = {}
        for c in cells:
            grid[(c["RowIndex"], c["ColumnIndex"])] = _text_of(c, by_id)
        body.append(f"\n#### Table {ti} — {rows} rows × {cols} cols ({len(cells)} cells)")
        body.append("")
        body.append("```")
        for r in range(1, min(rows, 12) + 1):
            cells_text = [grid.get((r, col), "")[:18] for col in range(1, cols + 1)]
            body.append(" | ".join(f"{x:<18}" for x in cells_text))
        if rows > 12:
            body.append(f"... ({rows - 12} more rows)")
        body.append("```")
    return "\n".join(body)


def _digest_layout(resp: dict) -> str:
    blocks = resp.get("Blocks", []) or []
    layout = [b for b in blocks if b.get("BlockType", "").startswith("LAYOUT_")]
    counts: dict[str, int] = defaultdict(int)
    for b in layout:
        counts[b["BlockType"]] += 1
    body = ["### Layout", f"- Layout blocks: **{len(layout)}**", "",
            "| block_type | count |", "|---|---|"]
    for bt in sorted(counts):
        body.append(f"| `{bt}` | {counts[bt]} |")
    return "\n".join(body)


def _digest_queries(resp: dict) -> str:
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    queries = [b for b in blocks if b.get("BlockType") == "QUERY"]
    body = ["### Queries", f"- Query blocks: **{len(queries)}**", "",
            "| alias | text | answer | conf |", "|---|---|---|---|"]
    for q in queries:
        meta = q.get("Query", {}) or {}
        alias = meta.get("Alias", "")
        text = meta.get("Text", "")
        ans_text = ""
        ans_conf = 0.0
        for rel in q.get("Relationships", []) or []:
            if rel["Type"] == "ANSWER":
                for rid in rel["Ids"]:
                    ans = by_id.get(rid)
                    if ans:
                        ans_text = ans.get("Text", "")
                        ans_conf = ans.get("Confidence", 0.0)
        body.append(
            f"| `{alias}` | {text} | `{ans_text}` | {ans_conf:.1f} |"
        )
    return "\n".join(body)


_DIGESTERS = {
    "detect": _digest_detect,
    "forms":  _digest_forms,
    "tables": _digest_tables,
    "layout": _digest_layout,
    "queries": _digest_queries,
}


def _digest_one(label: str, files: dict[str, Path]) -> str:
    out = [f"# {label}", ""]
    for feature in FEATURE_ORDER:
        if feature not in files:
            continue
        try:
            resp = json.loads(files[feature].read_text())
        except Exception as e:  # noqa: BLE001
            out.append(f"### {feature}\n_error parsing {files[feature]}: {e}_\n")
            continue
        out.append(_DIGESTERS[feature](resp))
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--in-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, dict[str, Path]] = defaultdict(dict)
    for f in sorted(args.in_dir.glob("*.json")):
        stem = f.stem
        if "__" not in stem:
            continue
        label, feature = stem.rsplit("__", 1)
        grouped[label][feature] = f

    if not grouped:
        print(f"no <label>__<feature>.json files in {args.in_dir}")
        return 1

    index_lines = ["# Textract Bake-Off Digests", ""]
    for label in sorted(grouped):
        digest = _digest_one(label, grouped[label])
        out_file = args.out_dir / f"{label}.md"
        out_file.write_text(digest)
        index_lines.append(f"- [{label}]({label}.md)")
        print(f"OK {out_file}")

    (args.out_dir / "index.md").write_text("\n".join(index_lines) + "\n")
    print(f"\nIndex: {args.out_dir / 'index.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
