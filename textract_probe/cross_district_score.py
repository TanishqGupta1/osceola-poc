"""Aggregate cross-district V4 results — per-district counts + spend.

D1 has GT PDFs; can additionally compute precision/recall via poc.eval.
D2-D7 have no GT; report ship rate + qualitative spot-check candidates.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

SHIP_GATE = 0.70


@dataclass
class Aggregate:
    district: int
    n_total: int = 0
    n_covers: int = 0
    n_indexes: int = 0
    n_separators: int = 0
    n_leaders: int = 0
    n_unknown: int = 0
    n_continuation: int = 0
    n_test_sheet: int = 0
    n_shipped: int = 0
    spend_usd: float = 0.0

    @property
    def ship_rate(self) -> float:
        return (self.n_shipped / self.n_covers) if self.n_covers else 0.0


CLASS_FIELD = {
    "student_cover":         "n_covers",
    "student_records_index": "n_indexes",
    "roll_separator":        "n_separators",
    "roll_leader":           "n_leaders",
    "student_continuation":  "n_continuation",
    "student_test_sheet":    "n_test_sheet",
    "unknown":               "n_unknown",
}


def aggregate_per_district(jsonl_path: Path) -> dict[int, Aggregate]:
    aggs: dict[int, Aggregate] = defaultdict(lambda: Aggregate(district=-1))
    with open(jsonl_path) as f:
        for ln in f:
            if not ln.strip():
                continue
            r = json.loads(ln)
            if "district" not in r:
                raise KeyError(f"row missing 'district' field: {r}")
            d = int(r["district"])
            a = aggs[d]
            a.district = d
            a.n_total += 1
            a.spend_usd += float(r.get("spend_usd", 0.0))
            cls = r.get("page_class", "unknown")
            field = CLASS_FIELD.get(cls)
            if field:
                setattr(a, field, getattr(a, field) + 1)
            if cls == "student_cover" and float(r.get("vote_confidence", 0.0)) >= SHIP_GATE:
                a.n_shipped += 1
    return dict(aggs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--results-jsonl", required=True, type=Path)
    args = p.parse_args(argv)

    aggs = aggregate_per_district(args.results_jsonl)
    print(f"{'D':<4}{'total':>7}{'cover':>8}{'cont':>7}{'test':>7}{'idx':>5}"
          f"{'sep':>5}{'lead':>6}{'unk':>5}{'ship':>6}{'rate':>8}{'$':>8}")
    print("-" * 80)
    grand = Aggregate(district=0)
    for d in sorted(aggs):
        a = aggs[d]
        print(
            f"{d:<4}{a.n_total:>7}{a.n_covers:>8}{a.n_continuation:>7}"
            f"{a.n_test_sheet:>7}{a.n_indexes:>5}{a.n_separators:>5}"
            f"{a.n_leaders:>6}{a.n_unknown:>5}{a.n_shipped:>6}"
            f"{a.ship_rate * 100:>7.1f}%{a.spend_usd:>8.3f}"
        )
        grand.n_total += a.n_total
        grand.n_covers += a.n_covers
        grand.n_continuation += a.n_continuation
        grand.n_test_sheet += a.n_test_sheet
        grand.n_indexes += a.n_indexes
        grand.n_separators += a.n_separators
        grand.n_leaders += a.n_leaders
        grand.n_unknown += a.n_unknown
        grand.n_shipped += a.n_shipped
        grand.spend_usd += a.spend_usd
    print("-" * 80)
    print(
        f"{'ALL':<4}{grand.n_total:>7}{grand.n_covers:>8}"
        f"{grand.n_continuation:>7}{grand.n_test_sheet:>7}"
        f"{grand.n_indexes:>5}{grand.n_separators:>5}{grand.n_leaders:>6}"
        f"{grand.n_unknown:>5}{grand.n_shipped:>6}"
        f"{grand.ship_rate * 100:>7.1f}%{grand.spend_usd:>8.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
