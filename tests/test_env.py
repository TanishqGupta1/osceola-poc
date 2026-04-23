import os
from unittest.mock import MagicMock, patch

from poc import env


def test_load_dotenvs_populates_process_env(tmp_path, monkeypatch):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)

    loaded = env.load_dotenvs(s3_path=s3, bedrock_path=br)
    assert loaded["s3"]["AWS_ACCESS_KEY_ID"] == "S3_KEY"
    assert loaded["bedrock"]["AWS_ACCESS_KEY_ID"] == "BR_KEY"


@patch("poc.env.boto3.client")
def test_s3_client_uses_s3_env(mock_boto, tmp_path):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    mock_boto.return_value = MagicMock()

    env.s3_client(s3_path=s3)
    args, kwargs = mock_boto.call_args
    assert args[0] == "s3"
    assert kwargs["aws_access_key_id"] == "S3_KEY"
    assert kwargs["region_name"] == "us-west-2"


@patch("poc.env.boto3.client")
def test_bedrock_client_uses_bedrock_env(mock_boto, tmp_path):
    s3 = tmp_path / ".env"
    br = tmp_path / ".env.bedrock"
    s3.write_text("AWS_ACCESS_KEY_ID=S3_KEY\nAWS_SECRET_ACCESS_KEY=S3_SECRET\n")
    br.write_text("AWS_ACCESS_KEY_ID=BR_KEY\nAWS_SECRET_ACCESS_KEY=BR_SECRET\n")
    mock_boto.return_value = MagicMock()

    env.bedrock_client(bedrock_path=br)
    args, kwargs = mock_boto.call_args
    assert args[0] == "bedrock-runtime"
    assert kwargs["aws_access_key_id"] == "BR_KEY"
    assert kwargs["region_name"] == "us-west-2"
