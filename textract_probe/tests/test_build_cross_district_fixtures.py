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
