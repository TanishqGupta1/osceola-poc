"""Self-contained Textract client factory. Reads repo-root .env.bedrock.

Kept separate from poc/env.py so the bake-off harness has zero coupling to the
production pipeline — can be deleted as a single directory if the no-LLM path
is abandoned.
"""
from __future__ import annotations

from pathlib import Path

import boto3
from dotenv import dotenv_values

DEFAULT_REGION = "us-west-2"
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BEDROCK_ENV = REPO_ROOT / ".env.bedrock"


def _load(path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv_values(path).items() if v}


def textract_client(
    bedrock_path: Path | str = DEFAULT_BEDROCK_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    env = _load(Path(bedrock_path))
    return boto3.client(
        "textract",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )
