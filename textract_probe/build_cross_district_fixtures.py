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
