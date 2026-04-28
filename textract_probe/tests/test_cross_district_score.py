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
        _row(1, "student_records_index", vote_confidence=0.99),  # high conf but NOT a cover; must NOT ship
    ]
    jsonl = tmp_path / "results.jsonl"
    jsonl.write_text("\n".join(json.dumps(r) for r in rows))

    aggs: dict[int, Aggregate] = aggregate_per_district(jsonl)

    assert aggs[1].n_total == 6
    assert aggs[1].n_covers == 3
    assert aggs[1].n_indexes == 2
    assert aggs[1].n_shipped == 2
    assert aggs[1].ship_rate == pytest.approx(2 / 3)
    assert aggs[1].spend_usd == pytest.approx(0.0885 * 3 + 0.015 + 0.0015 + 0.0015)

    assert aggs[2].n_covers == 2
    assert aggs[2].n_shipped == 1


def test_aggregate_raises_on_missing_district(tmp_path):
    jsonl = tmp_path / "broken.jsonl"
    jsonl.write_text(json.dumps({"page_class": "student_cover", "vote_confidence": 0.91, "spend_usd": 0.05}) + "\n")

    with pytest.raises(KeyError, match="district"):
        aggregate_per_district(jsonl)
