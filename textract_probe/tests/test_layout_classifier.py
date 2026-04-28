import pytest

from textract_probe import layout_classifier as lc


def _resp(blocks):
    return {"Blocks": blocks}


def _block(t, conf=99.0, text="", entity_types=None):
    b = {"BlockType": t, "Confidence": conf, "Text": text}
    if entity_types is not None:
        b["EntityTypes"] = entity_types
    return b


def test_classify_index_page():
    blocks = (
        [_block("LINE")] * 100
        + [_block("LAYOUT_TITLE")]
        + [_block("TABLE")]
        + [_block("CELL")] * 200
    )
    cls, conf, fp = lc.classify(_resp(blocks))
    assert cls == "student_records_index"
    assert conf >= 0.8
    assert fp["TABLE"] == 1


def test_classify_separator_styleA():
    blocks = (
        [_block("LINE")] * 6
        + [_block("LAYOUT_TITLE")] * 2
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_separator"


def test_classify_separator_styleB():
    blocks = (
        [_block("LINE")] * 26
        + [_block("LAYOUT_TITLE")]
        + [_block("KEY_VALUE_SET", conf=88.0, entity_types=["KEY"])] * 5
        + [_block("SIGNATURE")]
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_separator"


def test_classify_student_cover():
    blocks = (
        [_block("LINE")] * 200
        + [_block("KEY_VALUE_SET", conf=85.0, entity_types=["KEY"])] * 80
        + [_block("LAYOUT_FIGURE")]
        + [_block("SIGNATURE")] * 2
    )
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "student_cover"


def test_classify_roll_leader():
    blocks = [_block("LINE")] * 30
    cls, _, _ = lc.classify(_resp(blocks))
    assert cls == "roll_leader"


def test_classify_unknown():
    blocks = []
    cls, conf, _ = lc.classify(_resp(blocks))
    assert cls == "unknown"
    assert conf == 0.0
