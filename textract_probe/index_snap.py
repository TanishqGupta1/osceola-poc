"""Build roll-level index from Textract Tables responses + snap raw cover names.

Reuses field structure (`last`, `first`, `middle`, `dob`) used elsewhere in the
codebase but does NOT import from poc/ — keeps textract_probe/ isolated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import Levenshtein


@dataclass(frozen=True)
class IndexRow:
    last: str
    first: str
    middle: str
    dob: str


HEADER_HINTS = {
    "last":   ("LAST",),
    "first":  ("FIRST",),
    "middle": ("MIDDLE",),
    "dob":    ("DOB", "BIRTH"),
}


def _by_id(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {b["Id"]: b for b in blocks}


def _cell_text(cell: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> str:
    out: list[str] = []
    for rel in cell.get("Relationships", []) or []:
        if rel.get("Type") == "CHILD":
            for cid in rel.get("Ids", []):
                child = by_id.get(cid)
                if child and child.get("BlockType") == "WORD":
                    out.append((child.get("Text") or "").strip())
    return " ".join(out).strip()


def _resolve_header_columns(
    grid: dict[tuple[int, int], str], rows: int, cols: int
) -> dict[str, int]:
    header_row_idx = 1
    for r in range(1, min(4, rows + 1)):
        non_empty = sum(1 for c in range(1, cols + 1) if grid.get((r, c), "").strip())
        if non_empty >= 3:
            header_row_idx = r
            break

    mapping: dict[str, int] = {}
    for c in range(1, cols + 1):
        text = grid.get((header_row_idx, c), "").upper()
        for field, hints in HEADER_HINTS.items():
            if field in mapping:
                continue
            if any(h in text for h in hints):
                mapping[field] = c
                break
    mapping["__header_row__"] = header_row_idx
    return mapping


def parse_tables_into_index_rows(resp: dict[str, Any]) -> list[IndexRow]:
    """Parse all TABLE blocks in `resp` into IndexRow tuples."""
    blocks = resp.get("Blocks", []) or []
    by_id = _by_id(blocks)
    out: list[IndexRow] = []
    for t in blocks:
        if t.get("BlockType") != "TABLE":
            continue
        cells = []
        for rel in t.get("Relationships", []) or []:
            if rel.get("Type") == "CHILD":
                for cid in rel.get("Ids", []):
                    c = by_id.get(cid)
                    if c and c.get("BlockType") == "CELL":
                        cells.append(c)
        if not cells:
            continue
        rows = max(c["RowIndex"] for c in cells)
        cols = max(c["ColumnIndex"] for c in cells)
        grid: dict[tuple[int, int], str] = {}
        for c in cells:
            grid[(c["RowIndex"], c["ColumnIndex"])] = _cell_text(c, by_id)
        col_map = _resolve_header_columns(grid, rows, cols)
        if "last" not in col_map or "first" not in col_map:
            continue
        header_row = col_map["__header_row__"]
        for r in range(header_row + 1, rows + 1):
            last  = grid.get((r, col_map["last"]),   "").strip()
            first = grid.get((r, col_map["first"]),  "").strip()
            middle = grid.get((r, col_map.get("middle", -1)), "").strip()
            dob   = grid.get((r, col_map.get("dob", -1)),    "").strip()
            if not last and not first:
                continue
            out.append(IndexRow(last=last, first=first, middle=middle, dob=dob))
    return out


def snap_packet_name_to_index(
    last_raw: str,
    first_raw: str,
    middle_raw: str,
    index: list[IndexRow],
    *,
    max_last_distance: int = 2,
    max_first_distance: int = 2,
    max_total_distance: int = 3,
) -> IndexRow | None:
    """Match (last_raw, first_raw, middle_raw) to nearest IndexRow by Levenshtein."""
    if not index:
        return None
    last_q = (last_raw or "").strip().rstrip(",").upper()
    first_q = (first_raw or "").strip().upper()
    if not last_q:
        return None

    best: tuple[int, IndexRow] | None = None
    for row in index:
        d_last = Levenshtein.distance(last_q, row.last.upper())
        if d_last > max_last_distance:
            continue
        if first_q:
            d_first = Levenshtein.distance(first_q, row.first.upper())
            if d_first > max_first_distance:
                continue
            total = d_last + d_first
        else:
            total = d_last
        if total > max_total_distance:
            continue
        if best is None or total < best[0]:
            best = (total, row)
    return best[1] if best else None
