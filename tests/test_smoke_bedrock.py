import os
from pathlib import Path

import pytest

from poc.classify_extract import classify_page

SMOKE = os.environ.get("BEDROCK_SMOKE_TEST") == "1"
SAMPLES = Path("samples")

FIXTURES = [
    ("boundary_probe/t001_00005.tif",            "roll_separator"),
    ("verify_probe/d1r001_01923.tif",            "roll_separator"),
    ("test_input_roll001/00097.tif",             "student_cover"),
    ("boundary_probe/d3r028_00002.tif",          "roll_leader"),
    ("boundary_probe/d5r064_00001.tif",          "roll_leader"),
    ("index_probe/broad/d1r001/00011.tif",       "student_records_index"),
]


@pytest.mark.skipif(not SMOKE, reason="BEDROCK_SMOKE_TEST not set")
@pytest.mark.parametrize("rel_path,expected_class", FIXTURES)
def test_classify_fixture(rel_path, expected_class):
    tif = SAMPLES / rel_path
    assert tif.exists(), f"missing fixture: {tif}"
    r = classify_page(tif, roll_id="SMOKE")
    print(f"{rel_path}: predicted={r.page_class} conf={r.confidence_overall} "
          f"index_rows={len(r.index_rows)}")
    assert r.page_class == expected_class, (
        f"{rel_path}: expected {expected_class}, got {r.page_class}. "
        f"student={r.student} separator={r.separator}"
    )
    if expected_class == "student_records_index":
        assert len(r.index_rows) >= 10, \
            f"expected >=10 index rows, got {len(r.index_rows)}: {r.index_rows}"
