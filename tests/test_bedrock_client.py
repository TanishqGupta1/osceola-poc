from unittest.mock import MagicMock, patch

from poc.bedrock_client import classify_via_bedrock, compute_usd_cost


def _mock_converse_response(tool_input: dict, usage: dict | None = None) -> dict:
    return {
        "output": {
            "message": {
                "role": "assistant",
                "content": [
                    {"toolUse": {
                        "toolUseId": "tu_1",
                        "name": "classify_page",
                        "input": tool_input,
                    }}
                ],
            }
        },
        "stopReason": "tool_use",
        "usage": usage or {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
    }


_FAKE_INPUT = {
    "page_class": "student_cover",
    "separator": {"marker": None, "roll_no": None},
    "student": {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "", "school": ""},
    "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
    "index_rows": [],
    "confidence_overall": 0.9,
    "confidence_name": 0.88,
    "notes": "",
}


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_parses_tool_use(mock_factory):
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(_FAKE_INPUT)
    mock_factory.return_value = client

    tool_input, usage, usd_cost = classify_via_bedrock(b"fake_png_bytes")
    assert tool_input["page_class"] == "student_cover"
    assert usage["inputTokens"] == 1000
    assert usd_cost == 0.0015


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_retries_on_throttling(mock_factory):
    from botocore.exceptions import ClientError
    throttle = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")
    client = MagicMock()
    client.converse.side_effect = [
        throttle,
        _mock_converse_response({**_FAKE_INPUT, "page_class": "unknown"}),
    ]
    mock_factory.return_value = client

    tool_input, _usage, _usd = classify_via_bedrock(
        b"x", max_retries=2, retry_base_delay=0.01)
    assert tool_input["page_class"] == "unknown"
    assert client.converse.call_count == 2


@patch("poc.bedrock_client.env.bedrock_client")
def test_classify_via_bedrock_passes_max_tokens_1500(mock_factory):
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(_FAKE_INPUT)
    mock_factory.return_value = client

    classify_via_bedrock(b"x")
    _, kwargs = client.converse.call_args
    assert kwargs["inferenceConfig"]["maxTokens"] == 1500


def test_compute_usd_cost_formula():
    assert compute_usd_cost(2_000_000, 200_000) == 3.0
