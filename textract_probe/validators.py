"""Tier 1 deterministic validators — garbage filter, name regex, DOB checker.

Run on every extracted name/DOB candidate before it can vote in the
multi-source name voter. Fail-fast.
"""
from __future__ import annotations

import re

GARBAGE_TOKENS: frozenset[str] = frozenset({
    "BIRTH", "BIRTHDATE", "BIRTHPLACE", "BRITHDATE", "BRITHPLACE",
    "PLACE", "DATE", "AGE",
    "COUNTY", "STATE", "CITY", "SEX", "RACE", "GRADE", "GRADES",
    "NAME", "LAST", "FIRST", "MIDDLE", "RECORD", "RECORDS",
    "STUDENT", "PUPIL", "TEACHER", "COUNSELOR", "PARENT", "GUARDIAN",
    "ADDRESS", "PHONE", "OCCUPATION", "SCHOOL", "DISTRICT",
    "OSCEOLA", "FLORIDA", "ROLL", "NUMBER", "REEL", "REDUCTION",
    "CERTIFICATE", "AUTHENTICITY", "DEPARTMENT",
    "PHOTOGRAPH", "COMMENTS", "OBSERVATIONS", "SUGGESTIONS",
    "SECONDARY", "ELEMENTARY",
    "WITHDREW", "WITHDRAWN", "ENROLLED", "ENROLLMENT", "ENTRANCE",
    "TRANSFER", "TRANSFERRED", "GRADUATED", "DECEASED",
    "BEGAN", "ENDED", "RETURNED", "PROMOTED", "RETAINED",
})

PARENT_PREFIXES: tuple[str, ...] = (
    "MR.", "MRS.", "MS.", "DR.",
    "MOTHER", "FATHER", "GUARDIAN", "PARENT", "STEPFATHER", "STEPMOTHER",
)

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'\-\. ,]{1,60}[A-Za-z\.]$")

DOB_RE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\s*$")


def clean_extracted_name(s: str) -> str:
    """Strip trailing form noise like 'with', 'COUNTY', trailing punctuation."""
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"^['`\"]+", "", s)
    s = re.sub(r"[,\s]+$", "", s)
    for noise in (" with", " COUNTY", " (LAST)", " (FIRST)", " (MIDDLE)"):
        if s.endswith(noise):
            s = s[: -len(noise)].strip()
    return s.strip()


def is_valid_student_name(s: str) -> bool:
    if not s:
        return False
    cleaned = clean_extracted_name(s)
    if not cleaned or len(cleaned) < 3:
        return False
    if not NAME_RE.match(cleaned):
        return False
    upper = cleaned.upper()
    if upper.replace(" ", "").replace(",", "").isdigit():
        return False
    tokens = re.findall(r"[A-Za-z]+", upper)
    if any(t in GARBAGE_TOKENS for t in tokens):
        return False
    if any(upper.startswith(p) for p in PARENT_PREFIXES):
        return False
    return True


def is_valid_dob(s: str) -> bool:
    if not s:
        return False
    m = DOB_RE.match(s)
    if not m:
        return False
    mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mm <= 12) or not (1 <= dd <= 31):
        return False
    yyyy = yy if yy >= 100 else (1900 + yy if yy >= 30 else 2000 + yy)
    if not (1900 <= yyyy <= 2010):
        return False
    if mm == dd == yy:
        return False
    return True
