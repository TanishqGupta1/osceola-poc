from poc.schemas import (
    EvalReport,
    IndexRow,
    PageResult,
    RollMeta,
    Separator,
    Student,
    StudentPacket,
)


def test_page_result_minimal():
    r = PageResult(
        frame="00001",
        roll_id="ROLL 001",
        page_class="unknown",
        separator=Separator(marker=None, roll_no=None),
        student=Student(),
        roll_meta=RollMeta(),
        confidence_overall=0.0,
        confidence_name=0.0,
        model_version="test",
        processed_at="2026-04-18T00:00:00Z",
        latency_ms=0,
    )
    assert r.page_class == "unknown"
    assert r.student.last == ""


def test_page_class_enum_validation():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PageResult(
            frame="00001",
            roll_id="ROLL 001",
            page_class="bogus",
            separator=Separator(marker=None, roll_no=None),
            student=Student(),
            roll_meta=RollMeta(),
            confidence_overall=0.0,
            confidence_name=0.0,
            model_version="test",
            processed_at="2026-04-18T00:00:00Z",
            latency_ms=0,
        )


def test_student_packet():
    p = StudentPacket(
        packet_id="roll001_001",
        last_raw="SMITH", first_raw="JOHN", middle_raw="A",
        last="SMITH", first="JOHN", middle="A",
        frames=["00006", "00007"],
        flagged=False,
        avg_confidence=0.92,
    )
    assert p.frames == ["00006", "00007"]
    assert p.index_snap_applied is False


def test_page_class_accepts_student_records_index():
    r = PageResult(
        frame="00011",
        roll_id="ROLL 001",
        page_class="student_records_index",
        separator=Separator(marker=None, roll_no=None),
        student=Student(),
        roll_meta=RollMeta(),
        index_rows=[IndexRow(last="SMITH", first="JOHN", middle="A",
                             dob="3/4/1975", source_frame="00011")],
        confidence_overall=0.9,
        confidence_name=0.9,
        model_version="t",
        processed_at="2026-04-22T00:00:00Z",
        latency_ms=10,
    )
    assert r.page_class == "student_records_index"
    assert r.index_rows[0].last == "SMITH"


def test_page_result_default_empty_index_rows():
    r = PageResult(
        frame="00001", roll_id="ROLL 001", page_class="unknown",
        separator=Separator(marker=None, roll_no=None),
        student=Student(), roll_meta=RollMeta(),
        confidence_overall=0.0, confidence_name=0.0,
        model_version="t", processed_at="2026-04-22T00:00:00Z", latency_ms=0,
    )
    assert r.index_rows == []
    assert r.tokens_in == 0
    assert r.tokens_out == 0
    assert r.usd_cost == 0.0


def test_student_packet_has_raw_and_snap_fields():
    p = StudentPacket(
        packet_id="r001_001",
        last_raw="SNITH", first_raw="JOHN", middle_raw="A",
        last="SMITH", first="JOHN", middle="A",
        frames=["00006"],
        flagged=False,
        avg_confidence=0.9,
        index_snap_applied=True,
        index_snap_distance=1,
    )
    assert p.last_raw == "SNITH"
    assert p.last == "SMITH"
    assert p.index_snap_distance == 1


def test_eval_report_has_pre_post_and_diagnostics():
    e = EvalReport(
        roll_id="ROLL 001",
        pages_total=1924, pages_classified=1900,
        packets_predicted=419, packets_ground_truth=400,
        gt_rows_raw=419, gt_rows_usable=400,
        gt_rows_dropped_reasons={"placeholder": 14, "ocr_garbage": 3, "numeric_only": 2},
        exact_matches_pre=300, partial_matches_pre=60, no_match_pre=59,
        accuracy_exact_pre=0.716, accuracy_partial_pre=0.859,
        exact_matches_post=350, partial_matches_post=55, no_match_post=14,
        accuracy_exact_post=0.835, accuracy_partial_post=0.966,
        index_frames_total=7, index_rows_total=165,
        packets_snapped=42,
        usd_total=2.15, tokens_in_total=1_850_000, tokens_out_total=93_000,
        unmatched_predictions=[], unmatched_ground_truth=[],
    )
    assert e.accuracy_partial_post == 0.966
    assert e.gt_rows_dropped_reasons["placeholder"] == 14
