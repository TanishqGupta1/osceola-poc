from collections import Counter
from typing import Iterable

import Levenshtein

from poc.gt_clean import clean_gt_filename
from poc.schemas import EvalReport, StudentPacket


def _key(last: str, first: str) -> str:
    return f"{last}|{first}"


def _match_pass(
    packets: list[StudentPacket],
    gt_usable: list[dict[str, str]],
    get_last,
    get_first,
    get_middle,
    max_levenshtein: int,
) -> tuple[int, int, int, list[str], list[str]]:
    gt_used: set[int] = set()
    exact = 0
    partial = 0
    nomatch = 0
    unmatched_pred: list[str] = []
    for pkt in packets:
        pkt_last = get_last(pkt).upper().strip()
        pkt_first = get_first(pkt).upper().strip()
        pkt_middle = get_middle(pkt).upper().strip()

        best_idx = -1
        best_level = "none"

        for i, gt in enumerate(gt_usable):
            if i in gt_used:
                continue
            if gt["last"] == pkt_last and gt["first"] == pkt_first:
                if gt["middle"] == pkt_middle or not pkt_middle or not gt["middle"]:
                    best_idx = i
                    best_level = "exact"
                    break
                best_idx = i
                best_level = "partial"

        if best_level == "none":
            for i, gt in enumerate(gt_usable):
                if i in gt_used:
                    continue
                # Scale Lev cap with name length: long names tolerate more edits.
                cap_last = max_levenshtein + (1 if len(gt["last"]) >= 7 else 0)
                cap_first = max_levenshtein + (1 if len(gt["first"]) >= 7 else 0)
                if (Levenshtein.distance(gt["last"], pkt_last) <= cap_last
                        and Levenshtein.distance(gt["first"], pkt_first) <= cap_first):
                    best_idx = i
                    best_level = "partial"
                    break

        if best_level == "exact":
            exact += 1
            gt_used.add(best_idx)
        elif best_level == "partial":
            partial += 1
            gt_used.add(best_idx)
        else:
            nomatch += 1
            unmatched_pred.append(_key(pkt_last, pkt_first))

    unmatched_gt = [_key(gt_usable[i]["last"], gt_usable[i]["first"])
                    for i in range(len(gt_usable)) if i not in gt_used]
    return exact, partial, nomatch, unmatched_pred, unmatched_gt


def evaluate(
    packets: list[StudentPacket],
    ground_truth_filenames: Iterable[str],
    roll_id: str,
    max_levenshtein: int = 3,
    index_frames_total: int = 0,
    index_rows_total: int = 0,
) -> EvalReport:
    raw_list = list(ground_truth_filenames)
    gt_usable: list[dict[str, str]] = []
    drop_reasons: Counter[str] = Counter()

    for fn in raw_list:
        parsed, reason = clean_gt_filename(fn, return_reason=True, source_roll=roll_id)
        if parsed is None:
            drop_reasons[reason] += 1
        else:
            gt_usable.append(parsed)

    total = len(packets)

    exact_pre, partial_pre, no_pre, _upred_pre, _ugt_pre = _match_pass(
        packets, gt_usable,
        lambda p: p.last_raw, lambda p: p.first_raw, lambda p: p.middle_raw,
        max_levenshtein,
    )
    exact_post, partial_post, no_post, unmatched_pred_post, unmatched_gt_post = _match_pass(
        packets, gt_usable,
        lambda p: p.last, lambda p: p.first, lambda p: p.middle,
        max_levenshtein,
    )

    def _acc(num: int) -> float:
        return (num / total) if total else 0.0

    return EvalReport(
        roll_id=roll_id,
        pages_total=0,
        pages_classified=0,
        packets_predicted=total,
        packets_ground_truth=len(gt_usable),
        gt_rows_raw=len(raw_list),
        gt_rows_usable=len(gt_usable),
        gt_rows_dropped_reasons=dict(drop_reasons),
        exact_matches_pre=exact_pre,
        partial_matches_pre=partial_pre,
        no_match_pre=no_pre,
        accuracy_exact_pre=_acc(exact_pre),
        accuracy_partial_pre=_acc(exact_pre + partial_pre),
        exact_matches_post=exact_post,
        partial_matches_post=partial_post,
        no_match_post=no_post,
        accuracy_exact_post=_acc(exact_post),
        accuracy_partial_post=_acc(exact_post + partial_post),
        index_frames_total=index_frames_total,
        index_rows_total=index_rows_total,
        packets_snapped=sum(1 for p in packets if p.index_snap_applied),
        usd_total=0.0,
        tokens_in_total=0,
        tokens_out_total=0,
        unmatched_predictions=unmatched_pred_post,
        unmatched_ground_truth=unmatched_gt_post,
    )
