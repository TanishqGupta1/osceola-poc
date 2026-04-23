"""Ground-truth PDF filename normalization with drop-reason taxonomy.

See spec section "GT-cleaning pass" in
docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md.
"""
import re
from pathlib import Path

DROP_REASONS = {"placeholder", "ocr_garbage", "numeric_only", "too_short", "sham_merge"}

# Client-provided batch-merge PDFs, not per-student. Hardcoded exclusion.
SHAM_MERGE_ROLLS = {"ROLL 003", "ROLL 005", "ROLL 006"}

_PLACEHOLDER_RE = re.compile(r"\((?:LAST|FIRST|MIDDLE)\)", re.I)
_TRAILING_DUP = re.compile(r"_\d+$")
_OCR_GARBAGE_TOKENS = {
    "BIRTH", "COUNTY", "SEX", "PLACE", "CITY",
    "NAME", "LAST", "FIRST", "MIDDLE", "RECORD",
}


def _strip_numeric_prefix(tok: str) -> str:
    m = re.match(r"^\d+(.*)$", tok)
    return m.group(1) if m else tok


def clean_gt_filename(fname, *, return_reason=False, source_roll=""):
    """Parse and normalize a GT PDF filename.

    Args:
        fname: e.g. "SMITH, JOHN A.pdf"
        return_reason: when True, returns (result, reason) tuple. `result` is
            None for dropped rows.
        source_roll: e.g. "ROLL 003" (for sham-merge exclusion).

    Returns:
        dict {last, first, middle} or None if unusable.
    """
    def _fail(reason: str):
        return (None, reason) if return_reason else None

    def _ok(result: dict[str, str]):
        return (result, None) if return_reason else result

    if source_roll and source_roll in SHAM_MERGE_ROLLS:
        return _fail("sham_merge")

    stem = Path(fname).stem
    if _PLACEHOLDER_RE.search(stem):
        return _fail("placeholder")

    upper_stem = stem.upper()
    if any(tok in upper_stem for tok in _OCR_GARBAGE_TOKENS):
        return _fail("ocr_garbage")

    stem = _TRAILING_DUP.sub("", stem)

    if "," in stem:
        last, rest = stem.split(",", 1)
        tokens = rest.strip().split()
        first = tokens[0] if tokens else ""
        middle = " ".join(tokens[1:]) if len(tokens) > 1 else ""
    else:
        tokens = stem.split()
        if len(tokens) >= 2:
            last, first, *mid = tokens
            middle = " ".join(mid)
        elif tokens:
            last, first, middle = tokens[0], "", ""
        else:
            return _fail("too_short")

    last = last.strip()
    first = first.strip()

    if last.isdigit():
        return _fail("numeric_only")

    last = _strip_numeric_prefix(last)
    first = _strip_numeric_prefix(first)

    if not last or not first:
        return _fail("too_short")

    return _ok({
        "last": last.upper(),
        "first": first.upper(),
        "middle": middle.strip().upper(),
    })
