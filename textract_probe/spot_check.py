"""Print top-N high-confidence shipped covers per district as a markdown table.

Output: a 7-section markdown report. Each section lists the district's top-N
shipped covers sorted by vote_confidence (descending). Each row shows label,
vote_name, vote_confidence, and the rel_path so a human can open the TIF.

Use:
  python3 -m textract_probe.spot_check \
      --results-jsonl textract_probe/output/v4/crossd_v4_live_results.jsonl \
      --top-n 30 \
      --output textract_probe/output/v4/crossd_v4_spotcheck.md
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

LABEL_DISTRICT_RE = re.compile(r"^crossd_d(\d+)r")


def _district_of(row: dict) -> int:
    if "district" in row:
        return int(row["district"])
    m = LABEL_DISTRICT_RE.match(row.get("label", ""))
    return int(m.group(1)) if m else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--results-jsonl", required=True, type=Path)
    p.add_argument("--top-n", type=int, default=30)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args(argv)

    by_d: dict[int, list[dict]] = defaultdict(list)
    with open(args.results_jsonl) as f:
        for ln in f:
            r = json.loads(ln)
            if r.get("page_class") != "student_cover":
                continue
            if float(r.get("vote_confidence", 0)) < 0.70:
                continue
            by_d[_district_of(r)].append(r)

    lines: list[str] = ["# V4 Cross-District Spot-Check", ""]
    for d in sorted(by_d):
        rows = sorted(
            by_d[d], key=lambda x: -float(x.get("vote_confidence", 0))
        )[: args.top_n]
        lines.append(f"## District {d} - top {len(rows)} ships")
        lines.append("")
        lines.append("| label | name | conf | agree | sources | rel_path |")
        lines.append("|---|---|---|---|---|---|")
        for r in rows:
            lines.append(
                f"| {r.get('label','')} | `{r.get('vote_name','')}` | "
                f"{r.get('vote_confidence',0):.3f} | "
                f"{r.get('vote_agreement','')} | "
                f"{','.join(r.get('vote_sources', []))} | "
                f"`{r.get('rel_path','')}` |"
            )
        lines.append("")

    args.output.write_text("\n".join(lines))
    print(f"OK wrote spot-check to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
