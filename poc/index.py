"""Index-parse stage (H2.7 preparation).

Aggregates rows emitted by Bedrock on student_records_index pages,
dedupes on exact (last, first, dob) triples, and snaps grouped
student packets to the nearest index entry (Levenshtein <=2 per
component, <=3 sum).

See spec section "Index-parse stage" + "Index-snap algorithm" in
docs/superpowers/specs/2026-04-18-osceola-phase1-poc-design.md.
"""
import json
from pathlib import Path

import Levenshtein

from poc.schemas import IndexRow, PageResult, StudentPacket

COMPONENT_CAP = 2
SUM_CAP = 3


def build_roll_index(pages: list[PageResult]) -> list[IndexRow]:
    """Collect every index_rows entry from student_records_index pages, dedupe."""
    rows: list[IndexRow] = []
    seen: set[tuple[str, str, str]] = set()
    for p in pages:
        if p.page_class != "student_records_index":
            continue
        for r in p.index_rows:
            last = r.last.strip().upper()
            first = r.first.strip().upper()
            dob = r.dob.strip()
            if not last and not first:
                continue
            key = (last, first, dob)
            if key in seen:
                continue
            seen.add(key)
            rows.append(r)
    return rows


def snap_to_index(packet: StudentPacket, index: list[IndexRow]) -> StudentPacket:
    """Apply H2.7: snap (last_raw, first_raw) to nearest index entry within threshold."""
    if not index:
        return packet.model_copy(update={
            "last": packet.last_raw, "first": packet.first_raw, "middle": packet.middle_raw,
            "index_snap_applied": False, "index_snap_distance": None,
        })

    pkt_last = packet.last_raw.upper().strip()
    pkt_first = packet.first_raw.upper().strip()

    best_idx = -1
    best_dist = 1_000
    for i, entry in enumerate(index):
        if not entry.first.strip():
            continue
        d_last = Levenshtein.distance(pkt_last, entry.last.upper().strip())
        d_first = Levenshtein.distance(pkt_first, entry.first.upper().strip())
        if d_last > COMPONENT_CAP or d_first > COMPONENT_CAP:
            continue
        total = d_last + d_first
        if total > SUM_CAP:
            continue
        if total < best_dist:
            best_dist = total
            best_idx = i

    if best_idx < 0:
        return packet.model_copy(update={
            "last": packet.last_raw, "first": packet.first_raw, "middle": packet.middle_raw,
            "index_snap_applied": False, "index_snap_distance": None,
        })

    hit = index[best_idx]
    snapped_last = hit.last.upper().strip()
    snapped_first = hit.first.upper().strip()
    snapped_middle = hit.middle.upper().strip()
    applied = (snapped_last != pkt_last) or (snapped_first != pkt_first)
    return packet.model_copy(update={
        "last": snapped_last,
        "first": snapped_first,
        "middle": snapped_middle or packet.middle_raw,
        "index_snap_applied": applied,
        "index_snap_distance": best_dist,
    })


def write_index_json(rows: list[IndexRow], out_path: str | Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps([r.model_dump() for r in rows], indent=2))
