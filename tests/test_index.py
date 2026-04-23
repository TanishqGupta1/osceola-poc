import json
from pathlib import Path

from poc.index import build_roll_index, snap_to_index, write_index_json
from poc.schemas import IndexRow, PageResult, RollMeta, Separator, Student, StudentPacket


def _page(frame, cls, index_rows=None):
    return PageResult(
        frame=frame, roll_id="ROLL 001", page_class=cls,
        separator=Separator(), student=Student(), roll_meta=RollMeta(),
        index_rows=index_rows or [],
        confidence_overall=0.9, confidence_name=0.9,
        model_version="t", processed_at="2026-04-22T00:00:00Z", latency_ms=0,
    )


def _row(last, first, middle="", dob="", frame="00011"):
    return IndexRow(last=last, first=first, middle=middle, dob=dob, source_frame=frame)


def _packet(last_raw, first_raw, middle_raw="", packet_id="r001_001"):
    return StudentPacket(
        packet_id=packet_id,
        last_raw=last_raw, first_raw=first_raw, middle_raw=middle_raw,
        last=last_raw, first=first_raw, middle=middle_raw,
        frames=["00100"],
        flagged=False,
        avg_confidence=0.9,
    )


def test_build_roll_index_only_reads_index_pages():
    pages = [
        _page("00001", "roll_leader"),
        _page("00011", "student_records_index",
              [_row("SMITH", "JOHN"), _row("JONES", "MARY")]),
        _page("00050", "student_cover"),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 2
    assert rows[0].last == "SMITH"


def test_build_roll_index_dedupes_exact_triples():
    pages = [
        _page("00011", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75", frame="00011")]),
        _page("00018", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75", frame="00018")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 1


def test_build_roll_index_keeps_near_duplicates():
    pages = [
        _page("00011", "student_records_index",
              [_row("SMYTH", "JOHN", "A", "3/4/75")]),
        _page("00018", "student_records_index",
              [_row("SMITH", "JOHN", "A", "3/4/75")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 2


def test_build_roll_index_skips_blank_rows():
    pages = [
        _page("00011", "student_records_index",
              [_row("", ""), _row("SMITH", "JOHN")]),
    ]
    rows = build_roll_index(pages)
    assert len(rows) == 1


def test_snap_exact_match_sets_applied_false():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_applied is False
    assert out.index_snap_distance == 0


def test_snap_one_edit_corrects_and_marks_applied():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("SNITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_applied is True
    assert out.index_snap_distance == 1


def test_snap_three_edits_rejected():
    idx = [_row("SMITH", "JOHN")]
    p = _packet("GRAMT", "ALAN")
    out = snap_to_index(p, idx)
    assert out.last == "GRAMT"
    assert out.index_snap_applied is False
    assert out.index_snap_distance is None


def test_snap_component_cap_enforced():
    idx = [_row("ABCDE", "JOHN")]
    p = _packet("XYZDE", "JOHN")  # last-distance 3, first-distance 0
    out = snap_to_index(p, idx)
    assert out.index_snap_applied is False


def test_snap_picks_smallest_distance():
    idx = [_row("SMITH", "JOHN"), _row("SMYTH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.index_snap_distance == 0


def test_snap_empty_index_returns_packet_unchanged():
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, [])
    assert out.last == "SMITH"
    assert out.index_snap_applied is False
    assert out.index_snap_distance is None


def test_snap_skips_index_entry_with_blank_first_name():
    idx = [_row("SMITH", ""), _row("SMITH", "JOHN")]
    p = _packet("SMITH", "JOHN")
    out = snap_to_index(p, idx)
    assert out.last == "SMITH"
    assert out.first == "JOHN"


def test_write_index_json(tmp_path: Path):
    rows = [_row("SMITH", "JOHN", "A", "3/4/75"),
            _row("JONES", "MARY", "", "")]
    out = tmp_path / "roll_001_index.json"
    write_index_json(rows, out)
    data = json.loads(out.read_text())
    assert isinstance(data, list)
    assert data[0]["last"] == "SMITH"
    assert data[0]["source_frame"] == "00011"
