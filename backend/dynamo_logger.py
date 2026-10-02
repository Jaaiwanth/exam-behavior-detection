"""
backend/dynamo_logger.py — DynamoDB Behaviour Event Logger
==========================================================

Writes only behaviour warning events to DynamoDB.
Raw frames are NEVER stored.

Table schema (created by infra/dynamo_setup.py):
    Table name : exam_events
    PK         : student_id  (String)
    SK         : timestamp   (String, ISO-8601)
    Attributes : event_type, reason, score_after, session_id

Usage:
    from backend.dynamo_logger import log_event
    await log_event(student_id="s001", reason="Phone detected.", score_after=90)

If boto3 is not configured or DynamoDB is unreachable, the call logs a
warning and silently continues — it does NOT crash the WebSocket handler.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional boto3 import — degrades gracefully if not configured
# ---------------------------------------------------------------------------

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    _TABLE_NAME = os.environ.get("DYNAMO_TABLE", "exam_events")
    _AWS_REGION  = os.environ.get("AWS_REGION", "ap-south-1")

    _dynamodb = boto3.resource("dynamodb", region_name=_AWS_REGION)
    _table    = _dynamodb.Table(_TABLE_NAME)

    AVAILABLE = True
    logger.info("DynamoDB logger initialised (table=%s, region=%s)", _TABLE_NAME, _AWS_REGION)

except Exception as _exc:
    _dynamodb = _table = None
    BotoCoreError = ClientError = Exception
    AVAILABLE = False
    logger.warning(
        "DynamoDB logging disabled: %s\n"
        "Install boto3 and configure AWS credentials to enable.",
        _exc,
    )


# ---------------------------------------------------------------------------

def _write_event(student_id: str, reason: str, score_after: int, session_id: str) -> None:
    """Synchronous DynamoDB put_item — run in a thread via asyncio."""
    if not AVAILABLE:
        return
    try:
        _table.put_item(Item={
            "student_id":  student_id,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "event_type":  "WARNING",
            "reason":      reason,
            "score_after": score_after,
            "session_id":  session_id,
        })
        logger.debug("DynamoDB event written: student=%s reason=%s", student_id, reason)
    except (BotoCoreError, ClientError) as exc:
        logger.warning("DynamoDB write failed: %s", exc)


async def log_event(
    student_id: str,
    reason: str,
    score_after: int,
    session_id: str = "default",
) -> None:
    """
    Asynchronously write a behaviour warning event to DynamoDB.
    Non-blocking — runs the boto3 call in a thread pool executor.
    """
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        _write_event,
        student_id, reason, score_after, session_id,
    )
