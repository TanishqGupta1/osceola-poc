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
            "student": {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "", "school": ""},
            "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
            "index_rows": [],
            "confidence_overall": 0.9,
            "confidence_name": 0.88,
            "notes": "",
        },
        {"inputTokens": 1200, "outputTokens": 80, "totalTokens": 1280},
        0.0016,
    )
    tif = tmp_path / "00123.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.frame == "00123"
    assert r.roll_id == "ROLL 001"
    assert r.page_class == "student_cover"
    assert r.student.last == "SMITH"
    assert r.index_rows == []
    assert r.tokens_in == 1200
    assert r.tokens_out == 80
    assert r.usd_cost == 0.0016
    assert r.latency_ms >= 0


@patch("poc.classify_extract.classify_via_bedrock")
def test_classify_page_passes_through_index_rows(mock_call, tmp_path: Path):
    mock_call.return_value = (
        {
            "page_class": "student_records_index",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last": "", "first": "", "middle": "", "dob": "", "school": ""},
            "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
            "index_rows": [
                {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "3/4/75"},
                {"last": "JONES", "first": "MARY", "middle": "", "dob": ""},
            ],
            "confidence_overall": 0.95,
            "confidence_name": 0.9,
            "notes": "",
        },
        {"inputTokens": 1400, "outputTokens": 400, "totalTokens": 1800},
        0.0034,
    )
    tif = tmp_path / "00011.tif"
    _sample_tif(tif)
    r = classify_page(tif, roll_id="ROLL 001")
    assert r.page_class == "student_records_index"
    assert len(r.index_rows) == 2
    assert r.index_rows[0].last == "SMITH"
    assert r.index_rows[0].source_frame == "00011"
    assert r.index_rows[1].dob == ""
