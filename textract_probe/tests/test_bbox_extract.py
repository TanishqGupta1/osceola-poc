import pytest

from textract_probe import bbox_extract as bx


def _word(text, top, left, width=0.05, height=0.02, conf=95.0):
    return {
        "BlockType": "WORD",
        "Text": text,
        "Confidence": conf,
        "Geometry": {"BoundingBox": {"Top": top, "Left": left,
                                     "Width": width, "Height": height}},
    }


def test_extract_value_to_right_of_anchor():
    blocks = [
        _word("LAST", top=0.10, left=0.10, width=0.05),
        _word("Owen", top=0.10, left=0.18, width=0.06),
        _word("Title", top=0.05, left=0.10),
    ]
    val = bx.extract_value_near_anchor(
        blocks, anchor_text="LAST", direction="right"
    )
    assert val == "Owen"


def test_extract_value_below_anchor():
    blocks = [
        _word("NAME", top=0.10, left=0.10, width=0.05, height=0.02),
        _word("Janner", top=0.13, left=0.10),
        _word("Other", top=0.50, left=0.50),
    ]
    val = bx.extract_value_near_anchor(blocks, anchor_text="NAME", direction="below")
    assert val == "Janner"


def test_skip_label_words():
    blocks = [
        _word("LAST", top=0.10, left=0.10, width=0.05),
        _word("FIRST", top=0.10, left=0.18, width=0.06),
        _word("Owen", top=0.10, left=0.26, width=0.06),
    ]
    val = bx.extract_value_near_anchor(
        blocks, anchor_text="LAST", direction="right",
        skip_words={"FIRST", "MIDDLE", "DOB"},
    )
    assert val == "Owen"


def test_no_anchor_returns_empty():
    blocks = [_word("hello", top=0.1, left=0.1)]
    assert bx.extract_value_near_anchor(blocks, "MISSING", "right") == ""


def test_no_value_in_direction_returns_empty():
    blocks = [_word("LAST", top=0.5, left=0.5, width=0.05)]
    assert bx.extract_value_near_anchor(blocks, "LAST", "right") == ""
