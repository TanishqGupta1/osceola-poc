"""Textract bake-off harness.

Iterates fixtures × features, dumps raw JSON to --out-dir, prints summary
table to stdout. Halts on budget breach.

Usage:
  python3 -m textract_probe.bake_off \\
      --fixtures-file textract_probe/fixtures.json \\
      --out-dir textract_probe/output/textract \\
      --features detect,forms,tables,layout,queries \\
      --queries-file textract_probe/queries.json \\
      --budget-ceiling 1.50
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from textract_probe import client as tc
from textract_probe.convert import tif_to_png_bytes

SAMPLES = Path("samples")
ALL_FEATURES = ["detect", "forms", "tables", "layout", "queries"]


def _summarize(feature: str, resp: dict[str, Any]) -> str:
    blocks = resp.get("Blocks", []) or []
    if feature == "detect":
        return f"lines={sum(1 for b in blocks if b.get('BlockType') == 'LINE')}"
    if feature == "forms":
        keys = sum(
            1 for b in blocks
            if b.get("BlockType") == "KEY_VALUE_SET"
            and "KEY" in (b.get("EntityTypes") or [])
        )
        return f"kv_keys={keys}"
    if feature == "tables":
        n_tables = sum(1 for b in blocks if b.get("BlockType") == "TABLE")
        n_cells = sum(1 for b in blocks if b.get("BlockType") == "CELL")
        return f"tables={n_tables} cells={n_cells}"
    if feature == "layout":
        n = sum(1 for b in blocks if b.get("BlockType", "").startswith("LAYOUT_"))
        return f"layout_blocks={n}"
    if feature == "queries":
        n = sum(1 for b in blocks if b.get("BlockType") == "QUERY_RESULT")
        return f"answers={n}"
    return "?"


def _run_feature(feature: str, png: bytes, queries: list[dict] | None):
    if feature == "detect":
        return tc.detect_document_text(png)
    if feature == "forms":
        return tc.analyze_forms(png)
    if feature == "tables":
        return tc.analyze_tables(png)
    if feature == "layout":
        return tc.analyze_layout(png)
    if feature == "queries":
        if not queries:
            raise SystemExit("queries feature requested but --queries-file empty")
        return tc.analyze_queries(png, queries=queries)
    raise SystemExit(f"unknown feature: {feature}")


def _print_summary(rows, features, spend):
    print()
    print("=" * 110)
    header = f"{'fixture':<35}{'class':<24}" + "".join(f"{f:<22}" for f in features)
    print(header)
    print("-" * 110)
    for r in rows:
        cells = "".join(f"{str(r.get(f, '-')):<22}" for f in features)
        print(f"{r['label']:<35}{r['expected_class']:<24}{cells}")
    print("-" * 110)
    print(f"TOTAL SPEND: ${spend:.4f}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fixtures-file", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p.add_argument("--features", default=",".join(ALL_FEATURES))
    p.add_argument("--queries-file", type=Path, default=None)
    p.add_argument("--budget-ceiling", type=float, default=1.50)
    args = p.parse_args(argv)

    features = [f.strip() for f in args.features.split(",") if f.strip()]
    bad = [f for f in features if f not in ALL_FEATURES]
    if bad:
        raise SystemExit(f"unknown features: {bad}")

    fixtures = json.loads(args.fixtures_file.read_text())
    queries = json.loads(args.queries_file.read_text()) if args.queries_file else None

    args.out_dir.mkdir(parents=True, exist_ok=True)
    spend = 0.0
    rows: list[dict[str, Any]] = []

    for fx in fixtures:
        tif = SAMPLES / fx["rel_path"]
        if not tif.exists():
            print(f"SKIP missing: {tif}", file=sys.stderr)
            continue
        png = tif_to_png_bytes(tif)
        row = {"label": fx["label"], "expected_class": fx["expected_class"]}
        for feature in features:
            if spend >= args.budget_ceiling:
                print(
                    f"HALT: budget ceiling ${args.budget_ceiling} reached "
                    f"(spent ${spend:.4f})",
                    file=sys.stderr,
                )
                rows.append(row)
                _print_summary(rows, features, spend)
                return 2
            try:
                resp, cost = _run_feature(feature, png, queries)
            except Exception as e:  # noqa: BLE001
                row[feature] = f"ERR:{type(e).__name__}"
                print(f"ERR {fx['label']} {feature}: {e}", file=sys.stderr)
                continue
            spend += cost
            out_file = args.out_dir / f"{fx['label']}__{feature}.json"
            out_file.write_text(json.dumps(resp, default=str, indent=2))
            row[feature] = _summarize(feature, resp)
            print(
                f"OK {fx['label']:<35} {feature:<8} {row[feature]:<25} "
                f"${cost:.4f}  total=${spend:.4f}"
            )
        rows.append(row)

    _print_summary(rows, features, spend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
