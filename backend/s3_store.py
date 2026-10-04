"""
backend/s3_store.py — private S3 storage for warning recordings
================================================================

Recordings stay PRIVATE. Only the internal object key is stored in DynamoDB;
mentors get a short-lived presigned URL generated on demand by the backend.
No permanent public URL and no AWS credentials ever reach the browser.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

PRESIGN_EXPIRES_SEC = int(os.environ.get("PRESIGN_EXPIRES_SEC", "300"))   # 5 minutes

_client = None


def bucket_name() -> str:
    return os.environ.get("RECORDING_BUCKET", "jaaiwanth-exam-monitor-recordings")


def _get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.config import Config

        region = os.environ.get("AWS_REGION", "ap-south-1")
        # Pin the REGIONAL endpoint + SigV4. Without this the presigned URL can be built for the
        # global s3.amazonaws.com host but signed for ap-south-1, and S3 answers SignatureDoesNotMatch.
        _client = boto3.client(
            "s3",
            region_name=region,
            endpoint_url=f"https://s3.{region}.amazonaws.com",
            config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        )
    return _client


def reset_clients() -> None:
    global _client
    _client = None


def recording_key(exam_id: str, student_id: str, event_id: str) -> str:
    """Internal S3 key. Layout: recordings/<exam>/<student>/<event>.mp4"""
    return f"recordings/{exam_id}/{student_id}/{event_id}.mp4"


def upload_clip(key: str, data: bytes) -> bool:
    """Upload an MP4 clip. Returns True on success. Never raises."""
    try:
        _get_client().put_object(
            Bucket=bucket_name(), Key=key, Body=data, ContentType="video/mp4",
            ServerSideEncryption="AES256",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("S3 upload failed (%s): %s", key, exc)
        return False


def presign_get(key: str, expires: Optional[int] = None) -> str:
    """Temporary GET URL for one object (default 5 minutes)."""
    return _get_client().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket_name(),
            "Key": key,
            "ResponseContentType": "video/mp4",
            "ResponseContentDisposition": "inline",
        },
        ExpiresIn=expires or PRESIGN_EXPIRES_SEC,
    )
