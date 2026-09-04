"""
Thin wrapper around boto3 for the app's private S3 document bucket.

routers/document.py and services/scheduler.py only ever talk to S3 through the
functions in this module — no other module should import boto3 directly. The
bucket is private (Block Public Access on, no object ACLs), so the only way to
read an object is a short-lived presigned GET URL generated on demand.
"""
import contextlib
import logging
import os
import tempfile
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_PRESIGNED_URL_EXPIRE_SECONDS = int(os.getenv("S3_PRESIGNED_URL_EXPIRE_SECONDS", "600"))

_s3_client = None


def get_s3_client():
    """
    Lazy singleton — built on first use, not at import time, so importing this
    module (e.g. at FastAPI app startup) never fails just because AWS env vars
    aren't set yet (dev/test environments).
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            region_name=AWS_REGION,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
    return _s3_client


def upload_bytes(key: str, data: bytes, content_type: str) -> None:
    """Upload raw bytes to the private bucket under `key`. No ACL is set."""
    try:
        get_s3_client().put_object(
            Bucket=S3_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except (ClientError, BotoCoreError):
        logger.exception(f"S3 upload failed — key={key}")
        raise RuntimeError(f"Failed to upload object to S3: {key}")


def delete_object(key: str) -> None:
    """Delete an object from the bucket. Idempotent — no error if it's already gone."""
    try:
        get_s3_client().delete_object(Bucket=S3_BUCKET_NAME, Key=key)
    except (ClientError, BotoCoreError):
        logger.exception(f"S3 delete failed — key={key}")
        raise RuntimeError(f"Failed to delete object from S3: {key}")


def generate_presigned_download_url(key: str, expires_in: int | None = None) -> str:
    """
    Sign a time-limited GET URL for `key`. This is a local signing operation
    (no network call, no existence check) — it will happily sign a URL for a
    since-deleted key, which will simply 403 when used.
    """
    try:
        return get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in or S3_PRESIGNED_URL_EXPIRE_SECONDS,
        )
    except (ClientError, BotoCoreError):
        logger.exception(f"S3 presign failed — key={key}")
        raise RuntimeError(f"Failed to generate presigned URL for: {key}")


@contextlib.contextmanager
def s3_tempfile(key: str, suffix: str = ".pdf"):
    """
    Download `key` to a local temp file and yield its path — for code that
    can only work against a real filesystem path (PDF/text loaders). The temp
    file is always removed on the way out, including on exception.
    """
    fd, local_path = tempfile.mkstemp(suffix=suffix, prefix=f"s3_{uuid.uuid4().hex}_")
    os.close(fd)
    try:
        try:
            get_s3_client().download_file(S3_BUCKET_NAME, key, local_path)
        except (ClientError, BotoCoreError):
            logger.exception(f"S3 download failed — key={key}")
            raise RuntimeError(f"Failed to download object from S3: {key}")
        yield local_path
    finally:
        try:
            os.remove(local_path)
        except FileNotFoundError:
            pass
