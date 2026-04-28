import pytest

from textract_probe.index_snap import (
    parse_tables_into_index_rows,
    snap_packet_name_to_index,
    IndexRow,
)


def _table_resp(rows: list[list[str]]) -> dict:
    blocks: list[dict] = []
    word_id = 0
    table_id = "table-1"
    cell_relationships = []
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, cell_text in enumerate(row, start=1):
            cell_id = f"cell-{r_idx}-{c_idx}"
            children: list[str] = []
            for token in cell_text.split():
                word_id += 1
                wid = f"word-{word_id}"
                blocks.append({"BlockType": "WORD", "Id": wid, "Text": token})
                children.append(wid)
            blocks.append({
                "BlockType": "CELL",
                "Id": cell_id,
                "RowIndex": r_idx,
                "ColumnIndex": c_idx,
                "Relationships": [{"Type": "CHILD", "Ids": children}] if children else [],
            })
            cell_relationships.append(cell_id)
    blocks.append({
        "BlockType": "TABLE",
        "Id": table_id,
        "Relationships": [{"Type": "CHILD", "Ids": cell_relationships}],
    })
    return {"Blocks": blocks}


def test_parse_index_table_extracts_rows():
    resp = _table_resp([
        ["#", "STUDENT LAST NAME", "FIRST NAME", "MIDDLE NAME", "DOB"],
        ["1", "Carter",            "Marcia",     "Anne",        "5-7-62"],
        ["2", "Bunt",              "Judy",       "",            "9-3-65"],
    ])
    rows = parse_tables_into_index_rows(resp)
    assert len(rows) == 2
    assert rows[0].last == "Carter"
    assert rows[0].first == "Marcia"
    assert rows[0].middle == "Anne"
    assert rows[0].dob == "5-7-62"
    assert rows[1].last == "Bunt"
    assert rows[1].first == "Judy"


def test_snap_last_name_only_to_full_record():
    index = [
        IndexRow(last="Carter", first="Marcia", middle="Anne",  dob="5-7-62"),
        IndexRow(last="Bunt",   first="Judy",   middle="",      dob="9-3-65"),
        IndexRow(last="Owen",   first="Randall", middle="Horton", dob="11-26-45"),
    ]
    snapped = snap_packet_name_to_index(
        last_raw="Bunt", first_raw="", middle_raw="", index=index
    )
    assert snapped.last == "Bunt"
    assert snapped.first == "Judy"
    assert snapped.dob == "9-3-65"


def test_snap_with_levenshtein_tolerance():
    index = [
        IndexRow(last="Owen",   first="Randall", middle="Horton", dob="11-26-45"),
    ]
    snapped = snap_packet_name_to_index(
        last_raw="Owen,", first_raw="", middle_raw="", index=index
    )
    assert snapped is not None
    assert snapped.first == "Randall"


def test_snap_no_match_returns_none():
    index = [IndexRow(last="Carter", first="Marcia", middle="", dob="5-7-62")]
    snapped = snap_packet_name_to_index(
        last_raw="Zzzzz", first_raw="", middle_raw="", index=index
    )
    assert snapped is None
