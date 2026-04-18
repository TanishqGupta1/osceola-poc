import os

import boto3
from botocore.exceptions import ClientError


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def list_buckets():
    s3 = get_s3_client()
    try:
        response = s3.list_buckets()
        return response["Buckets"]
    except ClientError as e:
        print(f"Error listing buckets: {e}")
        return []


def list_objects(bucket, prefix=""):
    s3 = get_s3_client()
    try:
        params = {"Bucket": bucket}
        if prefix:
            params["Prefix"] = prefix
        response = s3.list_objects_v2(**params)
        return response.get("Contents", [])
    except ClientError as e:
        print(f"Error listing objects: {e}")
        return []


def upload_file(file_path, bucket, key=None):
    s3 = get_s3_client()
    if key is None:
        key = os.path.basename(file_path)
    try:
        s3.upload_file(file_path, bucket, key)
        print(f"Uploaded '{file_path}' to s3://{bucket}/{key}")
        return True
    except ClientError as e:
        print(f"Error uploading file: {e}")
        return False


def download_file(bucket, key, file_path=None):
    s3 = get_s3_client()
    if file_path is None:
        file_path = os.path.basename(key)
    try:
        s3.download_file(bucket, key, file_path)
        print(f"Downloaded s3://{bucket}/{key} to '{file_path}'")
        return True
    except ClientError as e:
        print(f"Error downloading file: {e}")
        return False


def read_object(bucket, key):
    s3 = get_s3_client()
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()
    except ClientError as e:
        print(f"Error reading object: {e}")
        return None


def delete_object(bucket, key):
    s3 = get_s3_client()
    try:
        s3.delete_object(Bucket=bucket, Key=key)
        print(f"Deleted s3://{bucket}/{key}")
        return True
    except ClientError as e:
        print(f"Error deleting object: {e}")
        return False
