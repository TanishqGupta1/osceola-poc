from poc.schemas import PageResult, StudentPacket, EvalReport, Separator, Student, RollMeta


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
        last="SMITH", first="JOHN", middle="A",
        frames=["00006","00007"],
        flagged=False,
        avg_confidence=0.92,
    )
    assert p.frames == ["00006","00007"]


def test_eval_report_defaults():
    e = EvalReport(
        roll_id="ROLL 001",
        pages_total=1924,
        pages_classified=1900,
        packets_predicted=419,
        packets_ground_truth=419,
        exact_name_matches=380,
        partial_name_matches=30,
        no_match=9,
        accuracy_exact=0.906,
        accuracy_partial=0.978,
        unmatched_predictions=[],
        unmatched_ground_truth=[],
    )
    assert e.accuracy_exact == 0.906
