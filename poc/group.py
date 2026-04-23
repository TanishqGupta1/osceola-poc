from collections import Counter

import Levenshtein

from poc.index import snap_to_index
from poc.schemas import IndexRow, PageResult, StudentPacket

PAGE_SNAP_COMPONENT_CAP = 3  # per-component Lev; looser than packet-level because
PAGE_SNAP_SUM_CAP = 4        # per-page names are noisier than packet majority


def _snap_page_name(
    raw_last: str, raw_first: str, index: list[IndexRow],
) -> tuple[str, str, str, int | None]:
    """Snap a single page's (last, first) to nearest index entry.

    Wider threshold than packet-level snap since raw per-page names are noisier.
    Also tries the swapped (first, last) order since Haiku occasionally inverts fields.
    Returns (last, first, middle, distance) — all empty + None if no match or empty input.
    """
    if not index:
        return raw_last, raw_first, "", None
    rl = raw_last.upper().strip()
    rf = raw_first.upper().strip()
    if not rl and not rf:
        return rl, rf, "", None

    best = None  # (dist, last, first, middle)
    for entry in index:
        if not entry.first.strip():
            continue
        el = entry.last.upper().strip()
        ef = entry.first.upper().strip()
        # try normal orientation
        d_last = Levenshtein.distance(rl, el)
        d_first = Levenshtein.distance(rf, ef)
        if (d_last <= PAGE_SNAP_COMPONENT_CAP
                and d_first <= PAGE_SNAP_COMPONENT_CAP
                and d_last + d_first <= PAGE_SNAP_SUM_CAP):
            total = d_last + d_first
            if best is None or total < best[0]:
                best = (total, el, ef, entry.middle.upper().strip())
        # try swapped (Haiku sometimes inverts first/last columns)
        d_last_sw = Levenshtein.distance(rl, ef)
        d_first_sw = Levenshtein.distance(rf, el)
        if (d_last_sw <= PAGE_SNAP_COMPONENT_CAP
                and d_first_sw <= PAGE_SNAP_COMPONENT_CAP
                and d_last_sw + d_first_sw <= PAGE_SNAP_SUM_CAP):
            total = d_last_sw + d_first_sw
            if best is None or total < best[0]:
                best = (total, el, ef, entry.middle.upper().strip())

    if best is None:
        return rl, rf, "", None
    return best[1], best[2], best[3], best[0]


def _normalize(p: PageResult) -> str:
    return f"{p.student.last.upper().strip()}|{p.student.first.upper().strip()[:3]}"


def _has_name(p: PageResult) -> bool:
    return bool(p.student.last.strip() or p.student.first.strip())


_STUDENT_CLASSES = {"student_cover", "student_test_sheet", "student_continuation"}

MERGE_COMPONENT_CAP = 2
MERGE_SUM_CAP = 3
MERGE_MAX_FRAME_GAP = 2  # allow up to 2-frame gap (e.g. a stray unknown between pages)


def _majority_name(pages: list[PageResult]) -> tuple[str, str, str]:
    """Pick most-common (last, first, middle) across pages with non-empty names."""
    named = [
        (p.student.last.upper().strip(),
         p.student.first.upper().strip(),
         p.student.middle.upper().strip())
        for p in pages
        if p.student.last.strip() or p.student.first.strip()
    ]
    if not named:
        return "", "", ""
    # Majority on (last, first) tuple; middle picked from pages matching that tuple.
    lf_counts: Counter[tuple[str, str]] = Counter((n[0], n[1]) for n in named)
    top_lf, _n = lf_counts.most_common(1)[0]
    # Middle: most-common non-empty middle among pages matching top (last, first).
    mids = [n[2] for n in named if (n[0], n[1]) == top_lf and n[2]]
    mid = Counter(mids).most_common(1)[0][0] if mids else ""
    return top_lf[0], top_lf[1], mid


def _frame_int(f: str) -> int:
    try:
        return int(f.lstrip("0") or "0")
    except ValueError:
        return 0


def _mergeable(a: StudentPacket, b: StudentPacket) -> bool:
    """H2.4: adjacent packets with Lev-close names and near-contiguous frames.

    Comparison uses POST-snap names (a.last/a.first) so packets that snap to the
    same canonical index entry merge deterministically, and noisy raw names that
    were corrected by H2.7 still get merged.
    """
    if not a.last or not b.last:
        return False
    d_last = Levenshtein.distance(a.last.upper(), b.last.upper())
    d_first = Levenshtein.distance(a.first.upper(), b.first.upper())
    if d_last > MERGE_COMPONENT_CAP or d_first > MERGE_COMPONENT_CAP:
        return False
    if d_last + d_first > MERGE_SUM_CAP:
        return False
    gap = _frame_int(b.frames[0]) - _frame_int(a.frames[-1])
    if gap < 0 or gap > (1 + MERGE_MAX_FRAME_GAP):
        return False
    return True


def _merge_pair(a: StudentPacket, b: StudentPacket,
                page_by_frame: dict[str, PageResult]) -> StudentPacket:
    """Combine two packets. Re-do majority-vote across both, preserve snap fields of the
    longer side if tied, otherwise recompute from merged frames."""
    merged_frames = a.frames + b.frames
    merged_pages = [page_by_frame[f] for f in merged_frames if f in page_by_frame]
    last, first, middle = _majority_name(merged_pages)
    confs = [p.confidence_name for p in merged_pages]
    avg = sum(confs) / len(confs) if confs else 0.0
    return StudentPacket(
        packet_id=a.packet_id,
        last_raw=last, first_raw=first, middle_raw=middle,
        last=last, first=first, middle=middle,
        frames=merged_frames,
        flagged=any(c < 0.7 for c in confs) or a.flagged or b.flagged,
        avg_confidence=avg,
        index_snap_applied=False,
        index_snap_distance=None,
    )


def _merge_adjacent(
    packets: list[StudentPacket],
    page_by_frame: dict[str, PageResult],
) -> list[StudentPacket]:
    """One pass over packets, greedily merging adjacent pairs that pass _mergeable."""
    if not packets:
        return packets
    out: list[StudentPacket] = [packets[0]]
    for nxt in packets[1:]:
        cur = out[-1]
        if _mergeable(cur, nxt):
            out[-1] = _merge_pair(cur, nxt, page_by_frame)
        else:
            out.append(nxt)
    return out


def group_by_index_entry(
    pages: list[PageResult],
    roll_index: list[IndexRow],
    confidence_threshold: float = 0.7,
    fallback_min_packet_size: int = 0,
    min_bucket_size: int = 1,
) -> list[StudentPacket]:
    """Alternate grouping: cluster all pages that snap to the same index row.

    One packet per unique index entry hit whose bucket has >= min_bucket_size
    pages (size-1 buckets are typically noise from isolated mis-snaps).
    Pages that don't snap are dropped unless `fallback_min_packet_size > 0`.
    """
    if not roll_index:
        return []

    pages = sorted(pages, key=lambda p: p.frame)
    start_idx = 0
    end_idx = len(pages)
    for i, p in enumerate(pages):
        if p.page_class == "roll_separator" and p.separator.marker == "START":
            start_idx = i + 1
            break
    for i in range(len(pages) - 1, -1, -1):
        if pages[i].page_class == "roll_separator" and pages[i].separator.marker == "END":
            end_idx = i
            break
    window = pages[start_idx:end_idx]

    # Map each named student-class page to its snapped (last, first) if within threshold.
    # Key by (last, first) only — middle name can vary by page, pick majority later.
    buckets: dict[tuple[str, str], list[tuple[PageResult, str]]] = {}
    confs: dict[tuple[str, str], list[float]] = {}
    unsnapped: list[PageResult] = []
    for p in window:
        if p.page_class not in _STUDENT_CLASSES:
            continue
        if not _has_name(p):
            if fallback_min_packet_size:
                unsnapped.append(p)
            continue
        sl, sf, sm, d = _snap_page_name(p.student.last, p.student.first, roll_index)
        if d is None:
            if fallback_min_packet_size:
                unsnapped.append(p)
            continue
        key = (sl, sf)
        buckets.setdefault(key, []).append((p, sm))
        confs.setdefault(key, []).append(p.confidence_name)

    # Produce StudentPacket per bucket, sorted by first-frame.
    packets: list[StudentPacket] = []
    roll_slug = pages[0].roll_id.lower().replace(" ", "")
    sorted_keys = sorted(
        buckets.keys(),
        key=lambda k: buckets[k][0][0].frame,
    )
    for i, key in enumerate(sorted_keys):
        last, first = key
        entries = buckets[key]
        if len(entries) < min_bucket_size:
            continue
        mids = [m for _, m in entries if m]
        middle = Counter(mids).most_common(1)[0][0] if mids else ""
        ps = [p for p, _ in entries]
        cs = confs[key]
        avg = sum(cs) / len(cs)
        packets.append(StudentPacket(
            packet_id=f"{roll_slug}_{i+1:03d}",
            last_raw=last, first_raw=first, middle_raw=middle,
            last=last, first=first, middle=middle,
            frames=[p.frame for p in ps],
            flagged=any(c < confidence_threshold for c in cs),
            avg_confidence=avg,
            index_snap_applied=True,
            index_snap_distance=0,
        ))

    # Fallback: name-change-group the unsnapped subset, keep clusters >= threshold.
    if fallback_min_packet_size and unsnapped:
        cur: list[PageResult] = []
        cur_confs_f: list[float] = []
        cur_key: str | None = None
        fallback_packets: list[StudentPacket] = []

        def flush_fb():
            nonlocal cur, cur_confs_f, cur_key
            if len(cur) >= fallback_min_packet_size:
                last, first, middle = _majority_name(cur)
                if last or first:
                    avg_f = sum(cur_confs_f) / len(cur_confs_f)
                    fallback_packets.append(StudentPacket(
                        packet_id="pending",
                        last_raw=last, first_raw=first, middle_raw=middle,
                        last=last, first=first, middle=middle,
                        frames=[p.frame for p in cur],
                        flagged=any(c < confidence_threshold for c in cur_confs_f),
                        avg_confidence=avg_f,
                    ))
            cur = []
            cur_confs_f = []
            cur_key = None

        for p in sorted(unsnapped, key=lambda x: x.frame):
            if not _has_name(p):
                if cur:
                    cur.append(p)
                    cur_confs_f.append(p.confidence_name)
                continue
            k = _normalize(p)
            if k != cur_key:
                flush_fb()
                cur_key = k
            cur.append(p)
            cur_confs_f.append(p.confidence_name)
        flush_fb()

        base = len(packets)
        for j, fp in enumerate(fallback_packets):
            packets.append(fp.model_copy(update={
                "packet_id": f"{roll_slug}_{base + j + 1:03d}",
            }))

    return packets


def group_pages(
    pages: list[PageResult],
    roll_index: list[IndexRow],
    confidence_threshold: float = 0.7,
    enable_merge: bool = True,
    enable_page_snap: bool = True,
) -> list[StudentPacket]:
    pages = sorted(pages, key=lambda p: p.frame)
    if not pages:
        return []

    start_idx = 0
    end_idx = len(pages)
    for i, p in enumerate(pages):
        if p.page_class == "roll_separator" and p.separator.marker == "START":
            start_idx = i + 1
            break
    for i in range(len(pages) - 1, -1, -1):
        if pages[i].page_class == "roll_separator" and pages[i].separator.marker == "END":
            end_idx = i
            break
    window = pages[start_idx:end_idx]

    # Pre-snap per-page names to index entries when possible. This collapses
    # the Haiku's per-page name variance onto the canonical roll index before
    # the name-change grouping decision runs.
    snapped_key: dict[str, tuple[str, str, str]] = {}
    if enable_page_snap and roll_index:
        for p in window:
            if p.page_class not in _STUDENT_CLASSES:
                continue
            if not _has_name(p):
                continue
            sl, sf, sm, _d = _snap_page_name(p.student.last, p.student.first, roll_index)
            snapped_key[p.frame] = (sl, sf, sm)

    def page_key(p: PageResult) -> str:
        if p.frame in snapped_key:
            sl, sf, _ = snapped_key[p.frame]
            return f"{sl}|{sf}"
        return _normalize(p)

    packets: list[StudentPacket] = []
    cur_pages: list[PageResult] = []
    cur_confs: list[float] = []
    cur_key: str | None = None

    def flush():
        nonlocal cur_pages, cur_confs, cur_key
        if not cur_pages:
            return
        last, first, middle = _majority_name(cur_pages)
        avg = sum(cur_confs) / len(cur_confs)
        pid = f"{pages[0].roll_id.lower().replace(' ', '')}_{len(packets)+1:03d}"
        raw_pkt = StudentPacket(
            packet_id=pid,
            last_raw=last, first_raw=first, middle_raw=middle,
            last=last, first=first, middle=middle,
            frames=[p.frame for p in cur_pages],
            flagged=any(c < confidence_threshold for c in cur_confs),
            avg_confidence=avg,
        )
        packets.append(snap_to_index(raw_pkt, roll_index))
        cur_pages = []
        cur_confs = []
        cur_key = None

    for p in window:
        if p.page_class not in _STUDENT_CLASSES:
            continue
        if not _has_name(p):
            if cur_pages:
                cur_pages.append(p)
                cur_confs.append(p.confidence_name)
            continue
        k = page_key(p)
        if k != cur_key:
            flush()
            cur_key = k
        cur_pages.append(p)
        cur_confs.append(p.confidence_name)
    flush()

    if enable_merge and packets:
        page_by_frame = {p.frame: p for p in pages}
        # Iterate merges to a fixed point (usually converges in 2-3 passes).
        for _ in range(5):
            merged = _merge_adjacent(packets, page_by_frame)
            if len(merged) == len(packets):
                break
            packets = merged
        # Re-apply snap on merged packets (names may have changed).
        packets = [snap_to_index(p, roll_index) for p in packets]
        # Re-number packet_ids after merge.
        roll_slug = pages[0].roll_id.lower().replace(" ", "")
        packets = [
            p.model_copy(update={"packet_id": f"{roll_slug}_{i+1:03d}"})
            for i, p in enumerate(packets)
        ]

    return packets
