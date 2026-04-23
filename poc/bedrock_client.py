import os
import time
from typing import Any

from botocore.exceptions import ClientError

from poc import env
from poc.prompts import MAX_OUTPUT_TOKENS, SYSTEM_PROMPT, TOOL_SCHEMA, USER_TURN_TEXT

DEFAULT_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)

# Haiku 4.5 pricing as of 2026-04: $1.00 / MTok input, $5.00 / MTok output.
HAIKU_IN_USD_PER_MTOK = 1.00
HAIKU_OUT_USD_PER_MTOK = 5.00


def compute_usd_cost(tokens_in: int, tokens_out: int) -> float:
    return (tokens_in / 1e6 * HAIKU_IN_USD_PER_MTOK) + (tokens_out / 1e6 * HAIKU_OUT_USD_PER_MTOK)


def classify_via_bedrock(
    png_bytes: bytes,
    model_id: str = DEFAULT_MODEL_ID,
    max_retries: int = 4,
    retry_base_delay: float = 1.0,
) -> tuple[dict[str, Any], dict[str, int], float]:
    """Call Bedrock Converse with image + enforced tool schema.

    Returns (tool_input, usage, usd_cost).
    """
    client = env.bedrock_client()

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
    for _attempt in range(max_retries):
        try:
            resp = client.converse(
                modelId=model_id,
                messages=messages,
                system=[{"text": SYSTEM_PROMPT}],
                toolConfig=tool_config,
                inferenceConfig={"maxTokens": MAX_OUTPUT_TOKENS, "temperature": 0.0},
            )
            content = resp["output"]["message"]["content"]
            usage = resp.get("usage", {}) or {}
            tokens_in = int(usage.get("inputTokens") or 0)
            tokens_out = int(usage.get("outputTokens") or 0)
            usd_cost = compute_usd_cost(tokens_in, tokens_out)
            for block in content:
                if "toolUse" in block:
                    return block["toolUse"]["input"], usage, usd_cost
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
