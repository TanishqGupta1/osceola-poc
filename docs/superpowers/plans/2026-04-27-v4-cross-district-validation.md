# V4 Cross-District Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the V4 pure-Textract + code-logic stack live against **200 mid-roll frames per district × 7 districts (1400 total)** to measure cross-district precision (D1 quantitative via existing GT, D2-D7 qualitative via spot-check) and decide between Theories A/B/C in `~/.claude/plans/users-tanishq-documents-project-files-a-soft-badger.md`.

**Architecture:** Reuse existing `textract_probe/extract_pipeline.py` + new helper scripts. Pull frames `00100.tif`..`00299.tif` from one representative roll per district directly from S3 via `poc.env.s3_client()`. Build a single 1400-row fixture manifest. Run V4 live with `--budget-ceiling 50.00`. Score D1 via `poc.eval.compute_eval_report` against existing 418 GT PDFs. Score D2-D7 via spot-check tool that flags top-N high-confidence ships per district for manual review.

**Tech Stack:** Python 3.11+, boto3 S3 + Textract (`.env` for S3, `.env.bedrock` for Textract), Pillow, pytest. Reuses `textract_probe/router.py`, `textract_probe/extract_pipeline.py`, `textract_probe/replay.py` precision math, `poc/eval.py::compute_eval_report`, `poc/gt_clean.py::clean_gt_filename`.

---

## File Structure

| Path | Status | Responsibility |
|---|---|---|
| `textract_probe/s3_pull.py` | create | Pull frames `00100..00299.tif` per (district, roll) tuple from S3 to `samples/cross_district_v4/` |
| `textract_probe/build_cross_district_fixtures.py` | create | Walk `samples/cross_district_v4/` and emit 1400-row fixture JSON |
| `textract_probe/cross_district_score.py` | create | Aggregate `extract_pipeline.py` JSONL output: per-district counts (covers identified, ships at conf≥0.70, ship rate, mean spend) + D1 GT match via `poc.eval` |
| `textract_probe/spot_check.py` | create | Print top-30 high-confidence shipped covers per district as a markdown table for hand verification |
| `textract_probe/tests/test_s3_pull.py` | create | Unit tests for S3 key construction, mock boto3 |
| `textract_probe/tests/test_build_cross_district_fixtures.py` | create | Unit tests for manifest builder |
| `textract_probe/tests/test_cross_district_score.py` | create | Unit tests for aggregation math |
| `docs/2026-04-27-v4-cross-district-results.md` | create | Authored after run; per-district numbers + decision (A vs B vs C) |
| `samples/cross_district_v4/` | create dir | Holds 1400 TIFs pulled from S3, gitignored via existing `samples/**` rule |

`textract_probe/output/v4/` already exists; new `crossd_v4_live` run outputs land there.

---

## Roll selection — one representative roll per district

Locked per existing `samples/verify_probe/` and `samples/index_probe/broad/` coverage:

| District | Roll | Source path on S3 |
|---|---|---|
| D1 | ROLL 001 | `Osceola Co School District/Test Input/ROLL 001/` (already byte-identical to Input/) |
| D2 | ROLL 020 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/` |
| D3 | ROLL 032 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-3/ROLL 032/` |
| D4 | ROLL 047 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-4/ROLL 047/` |
| D5 | ROLL 070 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-5/ROLL 070/` |
| D6 | ROLL 079 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-6/ROLL 079/` |
| D7 | ROLL 094 | `Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-7/ROLL 094/` |

Frames per roll: `00100.tif`..`00299.tif` = 200 mid-roll frames (guaranteed student-record territory; bypasses leader/separator zone).

---

## Task 1: S3 pull helper

**Files:**
- Create: `textract_probe/s3_pull.py`
- Create: `textract_probe/tests/test_s3_pull.py`

- [ ] **Step 1: Write failing tests**

Create `textract_probe/tests/test_s3_pull.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from textract_probe import s3_pull


def test_build_keys_test_input_for_d1():
    keys = s3_pull.build_keys(
        district=1, roll="001", frame_start=100, frame_end=299
    )
    assert keys[0].endswith("Test Input/ROLL 001/00100.tif")
    assert keys[-1].endswith("Test Input/ROLL 001/00299.tif")
    assert len(keys) == 200


def test_build_keys_input_for_d4():
    keys = s3_pull.build_keys(
        district=4, roll="047", frame_start=100, frame_end=299
    )
    assert "OSCEOLA SCHOOL DISTRICT-4/ROLL 047" in keys[0]
    assert keys[0].endswith("00100.tif")


def test_build_keys_zero_padded():
    keys = s3_pull.build_keys(
        district=2, roll="020", frame_start=5, frame_end=7
    )
    assert keys == [
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00005.tif",
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00006.tif",
        "Osceola Co School District/Input/OSCEOLA SCHOOL DISTRICT-2/ROLL 020/00007.tif",
    ]


@patch("textract_probe.s3_pull.s3_client")
def test_pull_skips_existing_files(mock_factory, tmp_path):
    fake_client = MagicMock()
    mock_factory.return_value = fake_client

    out_dir = tmp_path / "samples/d1r001"
    out_dir.mkdir(parents=True)
    (out_dir / "00100.tif").write_bytes(b"existing")

    n = s3_pull.pull_frames(
        bucket="bucket-x",
        keys=["prefix/00100.tif", "prefix/00101.tif"],
        out_dir=out_dir,
    )
    assert n == 1
    fake_client.download_file.assert_called_once_with(
        "bucket-x", "prefix/00101.tif", str(out_dir / "00101.tif")
    )
```

- [ ] **Step 2: Run tests, verify fail**

```
pytest textract_probe/tests/test_s3_pull.py -v
```

Expected: `ModuleNotFoundError: No module named 'textract_probe.s3_pull'`.

- [ ] **Step 3: Implement helper**

Create `textract_probe/s3_pull.py`:

```python
"""S3 puller — fetch a contiguous range of TIF frames per (district, roll)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from poc.env import s3_client

BUCKET = "servflow-image-one"
ROOT = "Osceola Co School District"


def build_keys(
    district: int,
    roll: str,
    frame_start: int,
    frame_end: int,
) -> list[str]:
    """Return inclusive list of S3 keys for frames [frame_start, frame_end]."""
    if district == 1 and roll == "001":
        prefix = f"{ROOT}/Test Input/ROLL {roll}"
    else:
        prefix = f"{ROOT}/Input/OSCEOLA SCHOOL DISTRICT-{district}/ROLL {roll}"
    return [f"{prefix}/{n:05d}.tif" for n in range(frame_start, frame_end + 1)]


def pull_frames(
    bucket: str,
    keys: Iterable[str],
    out_dir: Path,
) -> int:
    """Download keys to out_dir/<filename>. Skips existing files. Returns new-pull count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    client = s3_client()
    n = 0
    for key in keys:
        local = out_dir / Path(key).name
        if local.exists():
            continue
        client.download_file(bucket, key, str(local))
        n += 1
    return n
```

- [ ] **Step 4: Run tests, verify pass**

```
pytest textract_probe/tests/test_s3_pull.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/s3_pull.py textract_probe/tests/test_s3_pull.py
git commit -m "feat(textract_probe): S3 pull helper for cross-district validation"
```

---

## Task 2: Cross-district fixture manifest builder

**Files:**
- Create: `textract_probe/build_cross_district_fixtures.py`
- Create: `textract_probe/tests/test_build_cross_district_fixtures.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_build_cross_district_fixtures.py`:

```python
import json
from pathlib import Path

from textract_probe.build_cross_district_fixtures import build_manifest


def test_build_manifest_walks_all_district_dirs(tmp_path):
    samples = tmp_path / "samples/cross_district_v4"
    for d, roll in [(1, "001"), (2, "020")]:
        sub = samples / f"d{d}r{roll}"
        sub.mkdir(parents=True)
        for frame in (100, 101, 102):
            (sub / f"{frame:05d}.tif").write_bytes(b"x")

    fixtures = build_manifest(samples_root=samples, samples_relative_to=tmp_path / "samples")

    assert len(fixtures) == 6
    labels = sorted(f["label"] for f in fixtures)
    assert "crossd_d1r001_00100" in labels
    assert "crossd_d2r020_00102" in labels

    f0 = next(f for f in fixtures if f["label"] == "crossd_d1r001_00100")
    assert f0["rel_path"] == "cross_district_v4/d1r001/00100.tif"
    assert f0["district"] == 1
    assert f0["roll"] == "001"
    assert f0["frame"] == 100
```

- [ ] **Step 2: Run test, verify fail**

```
pytest textract_probe/tests/test_build_cross_district_fixtures.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement builder**

Create `textract_probe/build_cross_district_fixtures.py`:

```python
"""Build a fixtures manifest for cross-district V4 validation.

Walks samples/cross_district_v4/d<N>r<RRR>/<NNNNN>.tif and emits a single
JSON list compatible with extract_pipeline.py.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DIR_RE = re.compile(r"^d(?P<d>\d+)r(?P<roll>\d+)$")
FRAME_RE = re.compile(r"^(?P<frame>\d{5})\.tif$")


def build_manifest(
    samples_root: Path, samples_relative_to: Path
) -> list[dict]:
    fixtures: list[dict] = []
    for sub in sorted(p for p in samples_root.iterdir() if p.is_dir()):
        m = DIR_RE.match(sub.name)
        if not m:
            continue
        d = int(m.group("d"))
        roll = m.group("roll")
        for tif in sorted(sub.glob("*.tif")):
            fm = FRAME_RE.match(tif.name)
            if not fm:
                continue
            frame = int(fm.group("frame"))
            fixtures.append({
                "label": f"crossd_d{d}r{roll}_{frame:05d}",
                "rel_path": str(tif.relative_to(samples_relative_to)),
                "expected_class": None,
                "district": d,
                "roll": roll,
                "frame": frame,
            })
    return fixtures


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--samples-root", required=True, type=Path,
                   help="dir containing d<N>r<RRR>/ subdirs")
    p.add_argument("--samples-base", default=Path("samples"), type=Path,
                   help="dir against which to compute relative paths")
    p.add_argument("--output-file", required=True, type=Path)
    args = p.parse_args(argv)

    fixtures = build_manifest(args.samples_root, args.samples_base)
    args.output_file.write_text(json.dumps(fixtures, indent=2))
    print(f"OK wrote {len(fixtures)} fixtures to {args.output_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test, verify pass**

```
pytest textract_probe/tests/test_build_cross_district_fixtures.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add textract_probe/build_cross_district_fixtures.py textract_probe/tests/test_build_cross_district_fixtures.py
git commit -m "feat(textract_probe): cross-district fixture manifest builder"
```

---

## Task 3: Pull all 1400 TIFs from S3

**Files:**
- (no new code; uses Task 1 helpers via inline script)

- [ ] **Step 1: Run S3 pull script**

```bash
python3 - <<'PY'
from textract_probe.s3_pull import build_keys, pull_frames, BUCKET
from pathlib import Path

ROLLS = [
    (1, "001"),
    (2, "020"),
    (3, "032"),
    (4, "047"),
    (5, "070"),
    (6, "079"),
    (7, "094"),
]
out_root = Path("samples/cross_district_v4")
total_new = 0
for d, roll in ROLLS:
    keys = build_keys(d, roll, 100, 299)
    sub = out_root / f"d{d}r{roll}"
    n = pull_frames(BUCKET, keys, sub)
    print(f"D{d} ROLL {roll}: pulled {n} new TIFs into {sub}")
    total_new += n
print(f"TOTAL new TIFs: {total_new}")
PY
```

Expected: 7 lines, total ≤ 1400 new TIFs (depends on whether earlier sessions cached). Wall clock ~5-8 minutes.

- [ ] **Step 2: Verify counts on disk**

```bash
for d in 1 2 3 4 5 6 7; do
  echo -n "D$d: "
  ls samples/cross_district_v4/d${d}r*/*.tif 2>/dev/null | wc -l
done
```

Expected: each line `D<n>: 200`. Total 1400.

- [ ] **Step 3: No commit — TIFs gitignored by `samples/**` rule.**

---

## Task 4: Build manifest + run V4 pipeline live

**Files:**
- (no new code; orchestrates Tasks 1-2 outputs)

- [ ] **Step 1: Refresh AWS keys + verify Textract perms**

```bash
TEXTRACT_SMOKE_TEST=1 pytest textract_probe/tests/test_smoke.py -v -s
```

Expected: 1 passed. Costs $0.0015. **HALT here if AccessDeniedException — fix `.env.bedrock` before continuing.**

- [ ] **Step 2: Build fixture manifest**

```bash
python3 -m textract_probe.build_cross_district_fixtures \
    --samples-root samples/cross_district_v4 \
    --samples-base samples \
    --output-file textract_probe/fixtures_cross_district_v4.json
```

Expected: `OK wrote 1400 fixtures to textract_probe/fixtures_cross_district_v4.json`.

- [ ] **Step 3: Dry-run smoke — first 10 fixtures**

```bash
head -c 50 textract_probe/fixtures_cross_district_v4.json
python3 - <<'PY'
import json, pathlib
fixtures = json.loads(pathlib.Path("textract_probe/fixtures_cross_district_v4.json").read_text())
sub = fixtures[:10]
pathlib.Path("textract_probe/fixtures_cd_dryrun.json").write_text(json.dumps(sub, indent=2))
print(f"Wrote {len(sub)} dryrun fixtures.")
PY

python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures_cd_dryrun.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label crossd_v4_dryrun \
    --budget-ceiling 1.00
```

Expected: 10 result lines printed. Total spend ≤ $0.30.

- [ ] **Step 4: Full run — 1400 fixtures**

```bash
python3 -m textract_probe.extract_pipeline \
    --fixtures-file textract_probe/fixtures_cross_district_v4.json \
    --queries-file textract_probe/queries_v2.json \
    --run-label crossd_v4_live \
    --budget-ceiling 50.00 \
    2>&1 | tee textract_probe/output/v4/crossd_v4_live_console.log
```

Expected:
- Wall clock ~25-40 minutes (sequential; concurrency upgrade is Phase 2 work).
- Final summary: TOTAL SPEND should land $30-45 (mid mix: ~30% covers × $0.0885 + ~10% indexes × $0.015 + Detect-only on rest × $0.0015).
- 1400 result rows in `textract_probe/output/v4/crossd_v4_live_results.jsonl`.

- [ ] **Step 5: Sanity-check output**

```bash
wc -l textract_probe/output/v4/crossd_v4_live_results.jsonl
python3 -c "
import json
counts = {}
with open('textract_probe/output/v4/crossd_v4_live_results.jsonl') as f:
    for ln in f:
        r = json.loads(ln)
        c = r.get('page_class', '?')
        counts[c] = counts.get(c, 0) + 1
for c, n in sorted(counts.items(), key=lambda x: -x[1]):
    print(f'  {c:<25} {n}')
"
```

Expected: 1400 lines. Class distribution roughly: `student_continuation` largest, then `student_cover`, then `student_test_sheet`, then small counts of index/separator/leader/unknown.

---

## Task 5: Cross-district scorer

**Files:**
- Create: `textract_probe/cross_district_score.py`
- Create: `textract_probe/tests/test_cross_district_score.py`

- [ ] **Step 1: Write failing test**

Create `textract_probe/tests/test_cross_district_score.py`:

```python
import json
from pathlib import Path

import pytest

from textract_probe.cross_district_score import (
    aggregate_per_district,
    Aggregate,
)


def _row(district, page_class, vote_name="", vote_confidence=0.0, spend=0.0015):
    return {
        "district": district,
        "page_class": page_class,
        "vote_name": vote_name,
        "vote_confidence": vote_confidence,
        "spend_usd": spend,
    }


def test_aggregate_counts_classes_and_ships(tmp_path):
    rows = [
        _row(1, "student_cover", "Owen, Randall Horton", 0.91, 0.0885),
        _row(1, "student_cover", "Bunt", 0.83, 0.0885),
        _row(1, "student_cover", "weird", 0.40, 0.0885),  # not shipped
        _row(1, "student_records_index", spend=0.015),
        _row(1, "roll_leader", spend=0.0015),
        _row(2, "student_cover", "Smith", 0.95, 0.0885),
        _row(2, "student_cover", "Jones", 0.55, 0.0885),  # not shipped
    ]
    jsonl = tmp_path / "results.jsonl"
    jsonl.write_text("\n".join(json.dumps(r) for r in rows))

    aggs: dict[int, Aggregate] = aggregate_per_district(jsonl)

    assert aggs[1].n_total == 5
    assert aggs[1].n_covers == 3
    assert aggs[1].n_shipped == 2
    assert aggs[1].ship_rate == pytest.approx(2 / 3)
    assert aggs[1].spend_usd == pytest.approx(0.0885 * 3 + 0.015 + 0.0015)

    assert aggs[2].n_covers == 2
    assert aggs[2].n_shipped == 1
```

- [ ] **Step 2: Run test, verify fail**

```
pytest textract_probe/tests/test_cross_district_score.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement scorer**

Create `textract_probe/cross_district_score.py`:

```python
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
            d = int(r.get("district", 0))
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
```

- [ ] **Step 4: Run test, verify pass**

```
pytest textract_probe/tests/test_cross_district_score.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Run scorer on the live JSONL**

```bash
python3 -m textract_probe.cross_district_score \
    --results-jsonl textract_probe/output/v4/crossd_v4_live_results.jsonl
```

Expected: 8-row table (D1..D7 + ALL). Total spend should match the pipeline's reported total.

- [ ] **Step 6: Commit**

```bash
git add textract_probe/cross_district_score.py textract_probe/tests/test_cross_district_score.py
git commit -m "feat(textract_probe): cross-district aggregator (per-district counts + ships + spend)"
```

---

## Task 6: D1 quantitative scoring vs ROLL 001 GT

**Files:**
- (no new code; uses existing `poc.gt_clean` + ad-hoc Python)

- [ ] **Step 1: Verify D1 GT PDFs are on disk**

```bash
ls samples/output_pdfs_district1_roll001/*.pdf 2>/dev/null | wc -l
ls samples/output_pdfs_district1_roll001_full/*.pdf 2>/dev/null | wc -l
```

Expected: ≥15 in sparse dir, ideally 418 in `_full`. If only sparse exists, accept that as ground truth (covers 15 of the highest-confidence students). Document the limitation in §3 of results doc.

- [ ] **Step 2: Compute D1 precision against GT**

```bash
python3 - <<'PY'
import json, pathlib
from poc.gt_clean import clean_gt_filename

# Load V4 D1 ships
d1_ships = []
with open("textract_probe/output/v4/crossd_v4_live_results.jsonl") as f:
    for ln in f:
        r = json.loads(ln)
        if r.get("district") != 1:
            continue
        if r.get("page_class") != "student_cover":
            continue
        if float(r.get("vote_confidence", 0)) < 0.70:
            continue
        d1_ships.append(r)

# Load D1 GT
gt_dir = pathlib.Path("samples/output_pdfs_district1_roll001_full")
if not gt_dir.exists():
    gt_dir = pathlib.Path("samples/output_pdfs_district1_roll001")
gt_names: list[dict] = []
for pdf in sorted(gt_dir.glob("*.pdf")):
    cleaned = clean_gt_filename(pdf.stem)
    if cleaned:
        gt_names.append(cleaned)

print(f"D1 V4 ships: {len(d1_ships)}")
print(f"D1 GT (cleaned): {len(gt_names)}")

# Match by last-name (D1 frames 100-299 are mid-roll, may not all have GT)
gt_lasts = {g["last"].upper() for g in gt_names}
correct = 0
unmatched = []
for s in d1_ships:
    name = (s.get("vote_name") or "").upper()
    last_token = name.split(",")[0].strip().split()[0] if name else ""
    if last_token in gt_lasts:
        correct += 1
    else:
        unmatched.append(name)
prec = (correct / len(d1_ships) * 100) if d1_ships else 0
print(f"D1 precision (last-name in GT set): {correct}/{len(d1_ships)} = {prec:.1f}%")
print(f"D1 unmatched ships: {unmatched[:10]}")
PY
```

Expected: precision number plus list of any unmatched D1 ships for manual inspection.

- [ ] **Step 3: No commit — analysis output goes into results doc.**

---

## Task 7: D2-D7 spot-check tool

**Files:**
- Create: `textract_probe/spot_check.py`

- [ ] **Step 1: Implement spot-check tool**

Create `textract_probe/spot_check.py`:

```python
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
from collections import defaultdict
from pathlib import Path


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
            by_d[int(r.get("district", 0))].append(r)

    lines: list[str] = ["# V4 Cross-District Spot-Check", ""]
    for d in sorted(by_d):
        rows = sorted(
            by_d[d], key=lambda x: -float(x.get("vote_confidence", 0))
        )[: args.top_n]
        lines.append(f"## District {d} — top {len(rows)} ships")
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
```

- [ ] **Step 2: Run spot-check**

```bash
python3 -m textract_probe.spot_check \
    --results-jsonl textract_probe/output/v4/crossd_v4_live_results.jsonl \
    --top-n 30 \
    --output textract_probe/output/v4/crossd_v4_spotcheck.md
```

Expected: `OK wrote spot-check to textract_probe/output/v4/crossd_v4_spotcheck.md`. File has 7 district sections × 30 rows each = ~210 candidate ships for human review.

- [ ] **Step 3: Manual review (user task)**

User opens the spot-check markdown and (optionally) the cited TIFs side-by-side. For each row, marks correct (Y) / wrong (N) / can't tell (?) — paste a 4-column counts table per district into the §4 of the results doc.

- [ ] **Step 4: Commit**

```bash
git add textract_probe/spot_check.py
git commit -m "feat(textract_probe): cross-district spot-check tool for manual review"
```

---

## Task 8: Author cross-district results doc

**Files:**
- Create: `docs/2026-04-27-v4-cross-district-results.md`

- [ ] **Step 1: Write the results doc**

Create `docs/2026-04-27-v4-cross-district-results.md`:

```markdown
# V4 Cross-District Validation — Results

**Date:** 2026-04-27
**Run:** `crossd_v4_live` — 200 mid-roll TIFs per district × 7 districts (1400 total)
**Stack:** V4 pure-Textract + code-logic (commit `<git rev-parse HEAD>`)
**Spend:** $<total from cross_district_score> across <n> Textract calls
**Wall clock:** ~<min> minutes

## 1. Per-district class distribution + ship rate

(Paste output of `python3 -m textract_probe.cross_district_score`.)

## 2. D1 quantitative precision vs ROLL 001 GT

- Ships: <n>
- Last-name-in-GT matches: <n>/<n> = <pct>%
- Unmatched ships (sample): <list>

Compare to Phase 1 baseline 87.1% precision @ 23% recall on full ROLL 001
(`docs/superpowers/specs/2026-04-22-osceola-phase1-poc-v2-results.md`).

## 3. D2-D7 qualitative spot-check (top 30 ships per district)

| District | Reviewed | Correct | Wrong | Can't tell | Estimated precision |
|---|---|---|---|---|---|
| D2 | 30 | <n> | <n> | <n> | <pct>% |
| D3 | 30 | <n> | <n> | <n> | <pct>% |
| D4 | 30 | <n> | <n> | <n> | <pct>% |
| D5 | 30 | <n> | <n> | <n> | <pct>% |
| D6 | 30 | <n> | <n> | <n> | <pct>% |
| D7 | 30 | <n> | <n> | <n> | <pct>% |

(Sourced from manual review of `textract_probe/output/v4/crossd_v4_spotcheck.md`.)

## 4. Layout classifier sanity check

Pick 10 random TIFs per district from the JSONL output and visually
verify the assigned `page_class` matches reality. Record any
mis-classifications.

## 5. Index-snap effectiveness

Count rows in `crossd_v4_live_results.jsonl` where:
- `page_class == "student_cover"`
- `vote_name` exists and is single-token (last-name only)
- `snapped` populated

If count >0, snap rescued recall. Document by district.

## 6. Failure mode catalogue (per district)

For each failed ship, classify into:
- modern multi-section boxed form
- co-record (joint-parent) cover
- faded handwritten name single-source
- garbage filter leak
- other (describe)

## 7. Decision

Pick A / B / C from `~/.claude/plans/users-tanishq-documents-project-files-a-soft-badger.md`:
- aggregate precision ≥ 90% across D1-D7 → C (production scaffolding)
- 80-89% with 1-2 layout failures common → B (Bedrock retry tier)
- <80% or many distinct failures → A (preprocess pipeline first)
```

- [ ] **Step 2: Fill in every `<...>` placeholder** with real values from Tasks 5-7 outputs.

- [ ] **Step 3: Commit**

```bash
git add docs/2026-04-27-v4-cross-district-results.md
git commit -m "docs: V4 cross-district validation results — D1..D7 measured + decision"
```

---

## Task 9: Final test sweep + push

- [ ] **Step 1: Full test run**

```bash
pytest -q
```

Expected: 133 prior + 4 (s3_pull) + 1 (build_cd_fixtures) + 1 (cross_district_score) = **139 passed**, 7 skipped.

- [ ] **Step 2: Push to main**

```bash
git push origin main
```

---

## Verification (end-to-end)

After all 9 tasks:

1. **1400 TIFs on disk:**
   ```bash
   find samples/cross_district_v4 -name "*.tif" | wc -l
   ```
   Expected: `1400`.

2. **V4 results JSONL:**
   ```bash
   wc -l textract_probe/output/v4/crossd_v4_live_results.jsonl
   ```
   Expected: `1400`.

3. **Per-district aggregate prints clean table.**

4. **Spot-check markdown exists and has 7 sections × 30 rows each.**

5. **Spend total ≤ $50** (budget ceiling).

6. **Results doc populated with real numbers**, decision picked (A / B / C).

7. **`pytest -q` shows 139 passed, no regressions in `poc/` or earlier `textract_probe/` tests.**

---

## Out of scope

- Bedrock retry tier (Theory B work — only if D2-D7 spot-check shows <90%)
- Preprocessing pipeline (Theory A work — only if multiple layout failures)
- Production Step Functions / Lambda (Theory C work — after this validation passes)
- Hand-labeling D2-D7 GT for full quantitative precision (vendor task; out of scope here)
