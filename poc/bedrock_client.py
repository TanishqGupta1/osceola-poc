import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

from poc.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT

DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
DEFAULT_REGION = os.environ.get("AWS_REGION", "us-west-2")


def classify_via_bedrock(
    png_bytes: bytes,
    model_id: str = DEFAULT_MODEL_ID,
    region: str = DEFAULT_REGION,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Call Bedrock Converse with image + enforced tool schema. Returns (tool_input, usage)."""
    client = boto3.client("bedrock-runtime", region_name=region)

    messages = [
        {
            "role": "user",
            "content": [
                {"image": {"format": "png", "source": {"bytes": png_bytes}}},
                {"text": USER_TURN_TEXT},
            ],
        }
    ]
    tool_config = {
        "tools": [{"toolSpec": {
            "name": TOOL_SCHEMA["name"],
            "description": TOOL_SCHEMA["description"],
            "inputSchema": {"json": TOOL_SCHEMA["input_schema"]},
        }}],
        "toolChoice": {"tool": {"name": TOOL_SCHEMA["name"]}},
    }

    delay = retry_base_delay
    last_err: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": 1000, "temperature": 0.0},
            )
            content = resp["output"]["message"]["content"]
            for block in content:
                if "toolUse" in block:
                    return block["toolUse"]["input"], resp.get("usage", {})
            raise RuntimeError(f"no toolUse block: {content!r}")
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in {"ThrottlingException", "ServiceUnavailableException", "InternalServerException"}:
                last_err = e
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError(f"exhausted retries: {last_err!r}")
