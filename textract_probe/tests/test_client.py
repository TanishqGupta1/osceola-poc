from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from textract_probe import client as tc
from textract_probe import env


def test_textract_client_factory(tmp_path):
    fake_env = tmp_path / ".env.bedrock"
    fake_env.write_text(
        "AWS_ACCESS_KEY_ID=AKIATEST\n"
        "AWS_SECRET_ACCESS_KEY=secrettest\n"
        "AWS_REGION=us-west-2\n"
    )
    c = env.textract_client(bedrock_path=fake_env)
    assert c.meta.service_model.service_name == "textract"
    assert c.meta.region_name == "us-west-2"


@pytest.mark.parametrize("feature,pages,expected", [
    ("detect",  1, 0.0015),
    ("forms",   1, 0.05),
    ("tables",  1, 0.015),
    ("layout",  1, 0.004),
    ("queries", 1, 0.015),
    ("detect", 10, 0.015),
    ("forms",   3, 0.15),
])
def test_compute_textract_cost(feature, pages, expected):
    assert tc.compute_textract_cost(feature, pages) == pytest.approx(expected, rel=1e-9)


def test_compute_textract_cost_unknown_feature():
    with pytest.raises(KeyError):
        tc.compute_textract_cost("magic", 1)


@patch("textract_probe.client.env.textract_client")
def test_detect_document_text_happy_path(mock_factory):
    fake_resp = {"Blocks": [{"BlockType": "LINE", "Text": "ACKLEY, CALVIN"}]}
    fake_client = MagicMock()
    fake_client.detect_document_text.return_value = fake_resp
    mock_factory.return_value = fake_client

    resp, cost = tc.detect_document_text(b"PNGBYTES")

    assert resp == fake_resp
    assert cost == pytest.approx(0.0015)
    fake_client.detect_document_text.assert_called_once_with(
        Document={"Bytes": b"PNGBYTES"}
    )


@patch("textract_probe.client.time.sleep", return_value=None)
@patch("textract_probe.client.env.textract_client")
def test_detect_document_text_retries_on_throttle(mock_factory, _sleep):
    err = ClientError({"Error": {"Code": "ThrottlingException"}}, "DetectDocumentText")
    fake_client = MagicMock()
    fake_client.detect_document_text.side_effect = [err, err, {"Blocks": []}]
    mock_factory.return_value = fake_client

    resp, _cost = tc.detect_document_text(b"x", max_retries=3, retry_base_delay=0.0)

    assert resp == {"Blocks": []}
    assert fake_client.detect_document_text.call_count == 3


@patch("textract_probe.client.env.textract_client")
def test_detect_document_text_raises_non_retryable(mock_factory):
    err = ClientError({"Error": {"Code": "AccessDeniedException"}}, "DetectDocumentText")
    fake_client = MagicMock()
    fake_client.detect_document_text.side_effect = err
    mock_factory.return_value = fake_client

    with pytest.raises(ClientError):
        tc.detect_document_text(b"x")


@pytest.mark.parametrize("fn_name,feature,api_features", [
    ("analyze_forms",  "forms",  ["FORMS"]),
    ("analyze_tables", "tables", ["TABLES"]),
    ("analyze_layout", "layout", ["LAYOUT"]),
])
@patch("textract_probe.client.env.textract_client")
def test_analyze_simple_features(mock_factory, fn_name, feature, api_features):
    fake_resp = {"Blocks": [{"BlockType": "PAGE"}]}
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = fake_resp
    mock_factory.return_value = fake_client

    fn = getattr(tc, fn_name)
    resp, cost = fn(b"PNG")

    assert resp == fake_resp
    assert cost == pytest.approx(tc.TEXTRACT_PRICING_USD[feature])
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=api_features,
    )


@patch("textract_probe.client.env.textract_client")
def test_analyze_queries_passes_queries_config(mock_factory):
    fake_resp = {"Blocks": [{"BlockType": "QUERY_RESULT", "Text": "ACKLEY"}]}
    fake_client = MagicMock()
    fake_client.analyze_document.return_value = fake_resp
    mock_factory.return_value = fake_client

    queries = [
        {"Text": "What is the last name?", "Alias": "LAST"},
        {"Text": "What is the first name?", "Alias": "FIRST"},
    ]
    resp, cost = tc.analyze_queries(b"PNG", queries=queries)

    assert resp == fake_resp
    assert cost == pytest.approx(0.015)
    fake_client.analyze_document.assert_called_once_with(
        Document={"Bytes": b"PNG"},
        FeatureTypes=["QUERIES"],
        QueriesConfig={"Queries": queries},
    )


def test_analyze_queries_rejects_empty_queries():
    with pytest.raises(ValueError):
        tc.analyze_queries(b"PNG", queries=[])
