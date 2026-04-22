from pathlib import Path
from unittest.mock import patch
from PIL import Image

from poc.classify_extract import classify_page


def _sample_tif(path: Path):
    Image.new("L", (200, 300), color=255).save(path, format="TIFF")


@patch("poc.classify_extract.classify_via_bedrock")
def test_classify_page_builds_page_result(mock_call, tmp_path: Path):
    mock_call.return_value = (
        {
            "page_class": "student_cover",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last":"SMITH","first":"JOHN","middle":"A","dob":"","school":""},
            "roll_meta": {"filmer":"","date":"","school":"","reel_no_cert":""},
            "confidence_overall": 0.9,
            "confidence_name": 0.88,
            "notes": "",
        },
        {"inputTokens": 100, "outputTokens": 50, "totalTokens": 150},
    )
    tif = tmp_path / "00123.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.frame == "00123"
    assert r.roll_id == "ROLL 001"
    assert r.page_class == "student_cover"
    assert r.student.last == "SMITH"
    assert r.latency_ms >= 0
