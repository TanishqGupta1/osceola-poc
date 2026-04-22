import re
from pathlib import Path
from typing import Iterable

import Levenshtein

from poc.schemas import EvalReport, StudentPacket

_PLACEHOLDER_RE = re.compile(r"\(LAST\)|\(FIRST\)|\(MIDDLE\)", re.I)
_TRAILING_DUP = re.compile(r"_\d+$")


def parse_pdf_filename(fname: str) -> dict[str, str] | None:
    """Parse ground-truth PDF filename. Return None if placeholder (AI-failure case)."""
    stem = Path(fname).stem
    if _PLACEHOLDER_RE.search(stem):
        return None
    stem = _TRAILING_DUP.sub("", stem)
    if "," in stem:
        last, rest = stem.split(",", 1)
        rest = rest.strip()
        tokens = rest.split()
        first = tokens[0] if tokens else ""
        middle = " ".join(tokens[1:]) if len(tokens) > 1 else ""
    else:
        tokens = stem.split()
        if len(tokens) >= 2:
            last, first, *mid = tokens
            middle = " ".join(mid)
        elif tokens:
            last = tokens[0]; first = ""; middle = ""
        else:
            return None
    return {"last": last.upper().strip(), "first": first.upper().strip(), "middle": middle.upper().strip()}


def _key(last: str, first: str) -> str:
    return f"{last}|{first}"


def evaluate(
    packets: list[StudentPacket],
    ground_truth_filenames: Iterable[str],
    roll_id: str,
    max_levenshtein: int = 2,
) -> EvalReport:
    gt_parsed: list[dict[str, str]] = []
    for fn in ground_truth_filenames:
        p = parse_pdf_filename(fn)
        if p is not None:
            gt_parsed.append(p)

    gt_used: set[int] = set()
    exact = 0; partial = 0; nomatch = 0
    unmatched_pred: list[str] = []

    for pkt in packets:
        pkt_last = pkt.last.upper().strip()
        pkt_first = pkt.first.upper().strip()
        pkt_middle = pkt.middle.upper().strip()

        # exact match first
        best_idx = -1; best_level = "none"
        for i, gt in enumerate(gt_parsed):
            if i in gt_used:
                continue
            if gt["last"] == pkt_last and gt["first"] == pkt_first:
                if gt["middle"] == pkt_middle or not pkt_middle or not gt["middle"]:
                    best_idx = i; best_level = "exact"; break
                else:
                    best_idx = i; best_level = "partial"
        if best_level == "none":
            for i, gt in enumerate(gt_parsed):
                if i in gt_used:
                    continue
                if (Levenshtein.distance(gt["last"], pkt_last) <= max_levenshtein
                    and Levenshtein.distance(gt["first"], pkt_first) <= max_levenshtein):
                    best_idx = i; best_level = "partial"; break

        if best_level == "exact":
            exact += 1; gt_used.add(best_idx)
        elif best_level == "partial":
            partial += 1; gt_used.add(best_idx)
        else:
            nomatch += 1
            unmatched_pred.append(_key(pkt_last, pkt_first))

    unmatched_gt = [_key(gt_parsed[i]["last"], gt_parsed[i]["first"])
                    for i in range(len(gt_parsed)) if i not in gt_used]

    total_predicted = len(packets)
    return EvalReport(
        roll_id=roll_id,
        pages_total=0,
        pages_classified=0,
        packets_predicted=total_predicted,
        packets_ground_truth=len(gt_parsed),
        exact_name_matches=exact,
        partial_name_matches=partial,
        no_match=nomatch,
        accuracy_exact=(exact / total_predicted) if total_predicted else 0.0,
        accuracy_partial=((exact + partial) / total_predicted) if total_predicted else 0.0,
        unmatched_predictions=unmatched_pred,
        unmatched_ground_truth=unmatched_gt,
    )
