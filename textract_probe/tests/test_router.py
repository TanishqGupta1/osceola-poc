from unittest.mock import MagicMock, patch

import pytest

from textract_probe.router import process_page


@patch("textract_probe.router.tc")
def test_router_index_page_runs_detect_plus_tables(mock_tc):
    detect_resp = {
        "Blocks": (
            [{"BlockType": "LINE"}] * 100
            + [{"BlockType": "LAYOUT_TITLE"}]
            + [{"BlockType": "TABLE"}]
            + [{"BlockType": "CELL"}] * 200
        )
    }
    tables_resp = {"Blocks": [{"BlockType": "TABLE"}]}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)
    mock_tc.analyze_tables.return_value = (tables_resp, 0.015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "student_records_index"
    assert res["spend_usd"] == pytest.approx(0.0015 + 0.015)
    mock_tc.detect_document_text.assert_called_once()
    mock_tc.analyze_tables.assert_called_once()
    mock_tc.analyze_all.assert_not_called()


@patch("textract_probe.router.tc")
def test_router_cover_runs_detect_plus_combined(mock_tc):
    detect_resp = {
        "Blocks": (
            [{"BlockType": "LINE"}] * 200
            + [{"BlockType": "LAYOUT_FIGURE"}]
            + [{"BlockType": "KEY_VALUE_SET", "EntityTypes": ["KEY"]}] * 50
            + [{"BlockType": "SIGNATURE"}] * 2
        )
    }
    combined_resp = {"Blocks": [{"BlockType": "PAGE"}]}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)
    mock_tc.analyze_all.return_value = (combined_resp, 0.0885)

    queries = [{"Text": "Q?", "Alias": "A"}]
    res = process_page(b"PNG", queries=queries)

    assert res["page_class"] == "student_cover"
    assert res["spend_usd"] == pytest.approx(0.0015 + 0.0885)
    mock_tc.analyze_all.assert_called_once()


@patch("textract_probe.router.tc")
def test_router_separator_styleA_only_detect(mock_tc):
    detect_resp = {"Blocks": [{"BlockType": "LINE"}] * 8}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "roll_separator"
    assert res["spend_usd"] == pytest.approx(0.0015)
    mock_tc.analyze_all.assert_not_called()
    mock_tc.analyze_tables.assert_not_called()


@patch("textract_probe.router.tc")
def test_router_leader_only_detect(mock_tc):
    detect_resp = {"Blocks": [{"BlockType": "LINE"}] * 30}
    mock_tc.detect_document_text.return_value = (detect_resp, 0.0015)

    res = process_page(b"PNG", queries=None)

    assert res["page_class"] == "roll_leader"
    assert res["spend_usd"] == pytest.approx(0.0015)
    mock_tc.analyze_all.assert_not_called()
