from unittest.mock import MagicMock, patch

from poc.bedrock_client import classify_via_bedrock


def _mock_converse_response(tool_input: dict) -> dict:
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
        "usage": {"inputTokens": 1000, "outputTokens": 100, "totalTokens": 1100},
    }


@patch("poc.bedrock_client.boto3.client")
def test_classify_via_bedrock_parses_tool_use(mock_boto):
    fake_tool_input = {
        "page_class": "student_cover",
        "separator": {"marker": None, "roll_no": None},
        "student": {"last": "SMITH", "first": "JOHN", "middle": "A", "dob": "", "school": ""},
        "roll_meta": {"filmer": "", "date": "", "school": "", "reel_no_cert": ""},
        "confidence_overall": 0.9,
        "confidence_name": 0.88,
        "notes": "",
    }
    client = MagicMock()
    client.converse.return_value = _mock_converse_response(fake_tool_input)
    mock_boto.return_value = client

    result, usage = classify_via_bedrock(b"fake_png_bytes")
    assert result["page_class"] == "student_cover"
    assert result["student"]["last"] == "SMITH"
    assert usage["inputTokens"] == 1000


@patch("poc.bedrock_client.boto3.client")
def test_classify_via_bedrock_retries_on_throttling(mock_boto):
    from botocore.exceptions import ClientError
    client = MagicMock()
    # first call throttles, second succeeds
    throttle_err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}},
        "Converse",
    )
    client.converse.side_effect = [
        throttle_err,
        _mock_converse_response({
            "page_class": "unknown",
            "separator": {"marker": None, "roll_no": None},
            "student": {"last":"","first":"","middle":"","dob":"","school":""},
            "roll_meta": {"filmer":"","date":"","school":"","reel_no_cert":""},
            "confidence_overall": 0.1,
            "confidence_name": 0.0,
            "notes": "",
        }),
    ]
    mock_boto.return_value = client
    result, _ = classify_via_bedrock(b"x", max_retries=2, retry_base_delay=0.01)
    assert result["page_class"] == "unknown"
    assert client.converse.call_count == 2
