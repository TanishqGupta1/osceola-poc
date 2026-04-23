"""Dual-env loader. S3 creds live in .env; Bedrock creds live in .env.bedrock.

Pipeline modules MUST use s3_client() / bedrock_client() from this module.
Never call boto3.client() directly — that risks cross-contamination of creds
(Servflow-image1 cannot call Bedrock; tanishq cannot list S3).
"""
from pathlib import Path

import boto3
from dotenv import dotenv_values

DEFAULT_REGION = "us-west-2"
REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_S3_ENV = REPO_ROOT / ".env"
_DEFAULT_BEDROCK_ENV = REPO_ROOT / ".env.bedrock"


def _load(path: Path) -> dict[str, str]:
    values = dotenv_values(path)
    return {k: v for k, v in values.items() if v}


def load_dotenvs(
    s3_path: Path | str = _DEFAULT_S3_ENV,
    bedrock_path: Path | str = _DEFAULT_BEDROCK_ENV,
) -> dict[str, dict[str, str]]:
    """Return the parsed contents of both .env files without mutating os.environ."""
    return {
        "s3": _load(Path(s3_path)),
        "bedrock": _load(Path(bedrock_path)),
    }


def s3_client(
    s3_path: Path | str = _DEFAULT_S3_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    env = _load(Path(s3_path))
    return boto3.client(
        "s3",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )


def bedrock_client(
    bedrock_path: Path | str = _DEFAULT_BEDROCK_ENV,
    region: str = DEFAULT_REGION,
) -> boto3.client:
    env = _load(Path(bedrock_path))
    return boto3.client(
        "bedrock-runtime",
        aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
        region_name=env.get("AWS_REGION", region),
    )
