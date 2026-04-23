from poc.group import group_pages
from poc.schemas import IndexRow, PageResult, Separator, Student, RollMeta


def _pg(frame, cls, last="", first="", middle="", conf=0.9, marker=None, roll_no=None):
    return PageResult(
        frame=frame, roll_id="ROLL 001", page_class=cls,
        separator=Separator(marker=marker, roll_no=roll_no),
        student=Student(last=last, first=first, middle=middle),
        roll_meta=RollMeta(),
        confidence_overall=conf, confidence_name=conf,
        model_version="t", processed_at="2026-04-18T00:00:00Z", latency_ms=0,
    )


def test_groups_consecutive_same_name_with_raw_and_post_fields():
    pages = [
        _pg("00001", "roll_leader"),
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN"),
        _pg("00007", "student_continuation", "SMITH", "JOHN"),
        _pg("00008", "student_test_sheet", "JONES", "MARY"),
        _pg("00009", "student_cover", "JONES", "MARY"),
        _pg("01924", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 2
    assert packets[0].last_raw == "SMITH"
    assert packets[0].last == "SMITH"
    assert packets[0].index_snap_applied is False
    assert packets[0].frames == ["00006", "00007"]
    assert packets[1].last_raw == "JONES"
    assert packets[1].frames == ["00008", "00009"]


def test_index_pages_do_not_form_packets():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_records_index"),
        _pg("00007", "student_cover", "SMITH", "JOHN"),
        _pg("00999", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 1
    assert packets[0].last_raw == "SMITH"


def test_snap_applies_when_index_has_near_match():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SNITH", "JOHN"),
        _pg("00999", "roll_separator", marker="END", roll_no="1"),
    ]
    index = [IndexRow(last="SMITH", first="JOHN", source_frame="00011")]
    packets = group_pages(pages, roll_index=index)
    assert packets[0].last_raw == "SNITH"
    assert packets[0].last == "SMITH"
    assert packets[0].index_snap_applied is True
    assert packets[0].index_snap_distance == 1


def test_fallback_when_no_start_end():
    pages = [
        _pg("00001", "student_cover", "SMITH", "JOHN"),
        _pg("00002", "student_continuation", "SMITH", "JOHN"),
    ]
    packets = group_pages(pages, roll_index=[])
    assert len(packets) == 1


def test_low_confidence_flags_packet():
    pages = [
        _pg("00005", "roll_separator", marker="START", roll_no="1"),
        _pg("00006", "student_cover", "SMITH", "JOHN", conf=0.5),
        _pg("00007", "student_continuation", "SMITH", "JOHN", conf=0.95),
        _pg("00008", "roll_separator", marker="END", roll_no="1"),
    ]
    packets = group_pages(pages, roll_index=[], confidence_threshold=0.7)
    assert packets[0].flagged is True
