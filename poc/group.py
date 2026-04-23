from poc.index import snap_to_index
from poc.schemas import IndexRow, PageResult, StudentPacket


def _normalize(p: PageResult) -> str:
    return f"{p.student.last.upper().strip()}|{p.student.first.upper().strip()[:3]}"


def _has_name(p: PageResult) -> bool:
    return bool(p.student.last.strip() or p.student.first.strip())


_STUDENT_CLASSES = {"student_cover", "student_test_sheet", "student_continuation"}


def group_pages(
    pages: list[PageResult],
    roll_index: list[IndexRow],
    confidence_threshold: float = 0.7,
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

    packets: list[StudentPacket] = []
    cur_frames: list[str] = []
    cur_confs: list[float] = []
    cur_last = cur_first = cur_middle = ""
    cur_key: str | None = None

    def flush():
        nonlocal cur_frames, cur_confs, cur_last, cur_first, cur_middle, cur_key
        if not cur_frames:
            return
        avg = sum(cur_confs) / len(cur_confs)
        pid = f"{pages[0].roll_id.lower().replace(' ', '')}_{len(packets)+1:03d}"
        raw_pkt = StudentPacket(
            packet_id=pid,
            last_raw=cur_last, first_raw=cur_first, middle_raw=cur_middle,
            last=cur_last, first=cur_first, middle=cur_middle,
            frames=list(cur_frames),
            flagged=any(c < confidence_threshold for c in cur_confs),
            avg_confidence=avg,
        )
        packets.append(snap_to_index(raw_pkt, roll_index))
        cur_frames = []
        cur_confs = []
        cur_last = cur_first = cur_middle = ""
        cur_key = None

    for p in window:
        if p.page_class not in _STUDENT_CLASSES:
            continue
        if not _has_name(p):
            if cur_frames:
                cur_frames.append(p.frame)
                cur_confs.append(p.confidence_name)
            continue
        k = _normalize(p)
        if k != cur_key:
            flush()
            cur_key = k
            cur_last = p.student.last.upper().strip()
            cur_first = p.student.first.upper().strip()
            cur_middle = p.student.middle.upper().strip()
        cur_frames.append(p.frame)
        cur_confs.append(p.confidence_name)
    flush()
    return packets
