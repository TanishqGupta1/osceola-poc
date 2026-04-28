"""Bbox-positional value extractor.

When Textract Forms detects a label (e.g. `LAST`) but returns an empty VALUE,
fall back to scanning Detect WORD blocks for the nearest non-label word in
the expected direction (right of the label or directly below it). Used to
rescue handwritten name fields that Forms cannot pair on faded microfilm.
"""
from __future__ import annotations

from typing import Any, Iterable

DEFAULT_LABEL_WORDS: frozenset[str] = frozenset({
    "LAST", "FIRST", "MIDDLE", "NAME", "DOB", "BIRTH", "DATE",
    "PLACE", "BIRTHPLACE", "BIRTHDATE", "SCHOOL", "SEX", "RACE",
    "AGE", "GRADE", "ADDRESS", "PHONE", "PARENT", "MOTHER", "FATHER",
    "GUARDIAN", "PUPIL", "STUDENT", "RECORD", "OF", "OSCEOLA",
    "FLORIDA", "COUNTY", "ROLL", "NUMBER",
})


def _bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    g = block.get("Geometry", {}).get("BoundingBox")
    if not g:
        return None
    return g["Top"], g["Left"], g["Width"], g["Height"]


def extract_value_near_anchor(
    blocks: Iterable[dict[str, Any]],
    anchor_text: str,
    direction: str = "right",
    skip_words: Iterable[str] | None = None,
    max_horizontal_gap: float = 0.30,
    max_vertical_gap: float = 0.05,
) -> str:
    """Find a WORD block adjacent to an anchor WORD, in the given direction.

    direction = "right": same row (top within ±height), left > anchor_left+anchor_width.
    direction = "below": same column (left within ±width), top > anchor_top+anchor_height.

    Returns the candidate WORD's Text, or "" if none found.
    """
    skip = {w.upper() for w in (skip_words or DEFAULT_LABEL_WORDS)}
    anchor_text_u = anchor_text.upper()

    word_blocks = [b for b in blocks if b.get("BlockType") == "WORD"]

    anchor = None
    for b in word_blocks:
        if anchor_text_u == (b.get("Text") or "").upper():
            anchor = b
            break
    if anchor is None:
        return ""

    a_box = _bbox(anchor)
    if a_box is None:
        return ""
    a_top, a_left, a_width, a_height = a_box

    candidates: list[tuple[float, dict[str, Any]]] = []
    for b in word_blocks:
        if b is anchor:
            continue
        text = (b.get("Text") or "").strip()
        if not text or text.upper() in skip:
            continue
        bx_box = _bbox(b)
        if bx_box is None:
            continue
        b_top, b_left, b_width, b_height = bx_box

        if direction == "right":
            if abs(b_top - a_top) > a_height:
                continue
            gap = b_left - (a_left + a_width)
            if gap < -0.005 or gap > max_horizontal_gap:
                continue
            candidates.append((gap, b))
        elif direction == "below":
            if abs(b_left - a_left) > a_width:
                continue
            gap = b_top - (a_top + a_height)
            if gap < -0.005 or gap > max_vertical_gap:
                continue
            candidates.append((gap, b))
        else:
            raise ValueError(f"unknown direction: {direction!r}")

    if not candidates:
        return ""
    candidates.sort(key=lambda x: x[0])
    return (candidates[0][1].get("Text") or "").strip()
