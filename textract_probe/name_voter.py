"""Multi-source name voter — combines Forms, Queries, and Detect/regex sources.

Each candidate (source_name, raw_text, raw_textract_confidence_0_to_100) is run
through Tier 1 validators. Survivors are normalized and vote-clustered.

Winning cluster = largest agreement count; ties broken by sum-of-confidences.

Returned `confidence` is 0..1:
  - 3+ agreement -> 0.85 + min(0.10, top_conf * 0.001)
  - 2  agreement -> 0.75 + min(0.10, top_conf * 0.001)
  - 1  source    -> 0.40 + min(0.20, raw_conf * 0.002)
  - 0            -> 0.0
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from textract_probe.validators import clean_extracted_name, is_valid_student_name


@dataclass
class NameVote:
    name: str
    confidence: float
    agreement: int
    sources: list[str] = field(default_factory=list)


def _normalize_for_match(s: str) -> str:
    s = clean_extracted_name(s).lower()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip(" ,")
    return s


def vote_on_name(
    sources: list[tuple[str, str, float]],
) -> NameVote:
    """sources = list of (source_name, raw_text, raw_textract_confidence)."""
    valid: list[tuple[str, str, str, float]] = []
    for src, raw, conf in sources:
        cleaned = clean_extracted_name(raw)
        if not is_valid_student_name(cleaned):
            continue
        norm = _normalize_for_match(cleaned)
        valid.append((src, cleaned, norm, conf))

    if not valid:
        return NameVote(name="", confidence=0.0, agreement=0, sources=[])

    clusters: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for src, cleaned, norm, conf in valid:
        clusters[norm].append((src, cleaned, conf))

    def cluster_key(item: tuple[str, list[tuple[str, str, float]]]):
        norm, members = item
        return (len(members), sum(m[2] for m in members))

    winner_norm, winner_members = max(clusters.items(), key=cluster_key)
    agreement = len(winner_members)
    top_conf = max(m[2] for m in winner_members)
    canonical = max(winner_members, key=lambda m: m[2])[1]
    sources_used = [m[0] for m in winner_members]

    if agreement >= 3:
        score = 0.85 + min(0.10, top_conf * 0.001)
    elif agreement == 2:
        score = 0.75 + min(0.10, top_conf * 0.001)
    elif agreement == 1:
        score = 0.40 + min(0.20, top_conf * 0.002)
    else:
        score = 0.0

    return NameVote(
        name=canonical,
        confidence=round(score, 3),
        agreement=agreement,
        sources=sources_used,
    )
