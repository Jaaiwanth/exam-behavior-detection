"""
backend/dynamo_logger.py — DynamoDB behaviour events + manual-review state
==========================================================================

Table (created by infra/dynamo_setup.py):
    Table name : exam_events
    PK         : exam_id    (String)
    SK         : sort_key   (String)
    GSI        : student-index  (student_id, sort_key)

Two kinds of items share the table:

1. WARNING EVENT      sort_key = "<iso-timestamp>#<student_id>#<event_id8>"
     exam_id, student_id, event_id, timestamp, event_type="WARNING",
     warning_type, sanity_score, flagged (True when score reached 0),
     session_id, review_status, recording_status,
     s3_object_key (internal S3 key — set once the clip upload finishes;
                    NEVER a public URL),
     + reviewed_by / reviewed_at / mentor_decision / mentor_notes after review

2. SESSION REVIEW     sort_key = "SESSION#<student_id>"
     One per student per exam. This is what the mentor dashboard lists.
     review_status: NOT_REQUIRED | PENDING_REVIEW | CLEARED | CONFIRMED_VIOLATION
     A score of 0 only moves NOT_REQUIRED -> PENDING_REVIEW. It never marks a
     student as cheating: only a mentor's decision does.

Raw frames are never stored here. If boto3 / AWS is unavailable the write
functions log a warning and carry on, so the monitoring WebSocket never crashes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# review_status values
NOT_REQUIRED       = "NOT_REQUIRED"
PENDING_REVIEW     = "PENDING_REVIEW"
CLEARED            = "CLEARED"
CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
DECISIONS = {CLEARED, CONFIRMED_VIOLATION}

SESSION_PREFIX = "SESSION#"

_table = None


def _get_table():
    """Lazily create the boto3 Table so tests can patch AWS before first use."""
    global _table
    if _table is None:
        import boto3
        name   = os.environ.get("DYNAMO_TABLE", "exam_events")
        region = os.environ.get("AWS_REGION", "ap-south-1")
        _table = boto3.resource("dynamodb", region_name=region).Table(name)
        logger.info("DynamoDB table handle ready (table=%s, region=%s)", name, region)
    return _table


def reset_clients() -> None:
    """Forget cached boto3 handles (used by tests)."""
    global _table
    _table = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(item: Dict[str, Any]) -> Dict[str, Any]:
    """Convert DynamoDB Decimals to ints/floats so FastAPI can serialise them."""
    out: Dict[str, Any] = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            out[k] = int(v) if v == v.to_integral_value() else float(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Writes (called from the monitoring WebSocket)
# ---------------------------------------------------------------------------

def create_event(
    exam_id: str,
    student_id: str,
    warning_type: str,
    sanity_score: int,
    session_id: str = "default",
    warning_count: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Write one warning event and update the session-review record.
    Returns the stored event (with event_id / sort_key) or None on failure.
    """
    from botocore.exceptions import BotoCoreError, ClientError

    event_id = uuid.uuid4().hex
    ts       = _now()
    flagged  = sanity_score <= 0
    event = {
        "exam_id":          exam_id,
        "sort_key":         f"{ts}#{student_id}#{event_id[:8]}",
        "student_id":       student_id,
        "event_id":         event_id,
        "timestamp":        ts,
        "event_type":       "WARNING",
        "warning_type":     warning_type,
        "sanity_score":     int(sanity_score),
        "flagged":          flagged,
        "session_id":       session_id,
        # Only the score-0 event is itself queued for review; the session record is the source of truth.
        "review_status":    PENDING_REVIEW if flagged else NOT_REQUIRED,
        "recording_status": "PENDING",
    }
    try:
        table = _get_table()
        table.put_item(Item=event)
        _update_session(table, exam_id, student_id, session_id, sanity_score, warning_count, ts, flagged)
        return event
    except (BotoCoreError, ClientError, Exception) as exc:  # noqa: BLE001 — never crash the WS
        logger.warning("DynamoDB write failed: %s", exc)
        return None


def _update_session(table, exam_id, student_id, session_id, score, warning_count, ts, flagged) -> None:
    from botocore.exceptions import ClientError

    key = {"exam_id": exam_id, "sort_key": f"{SESSION_PREFIX}{student_id}"}
    table.update_item(
        Key=key,
        UpdateExpression=(
            "SET student_id = :sid, session_id = :sess, event_type = :et, "
            "last_score = :score, last_event_at = :ts, "
            "review_status = if_not_exists(review_status, :none) "
            "ADD warning_count :one"
        ),
        ExpressionAttributeValues={
            ":sid": student_id, ":sess": session_id, ":et": "SESSION_REVIEW",
            ":score": int(score), ":ts": ts, ":none": NOT_REQUIRED, ":one": 1,
        },
    )
    if flagged:
        # Score reached 0 -> requires manual review. Never overwrite a mentor decision.
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET review_status = :p, flagged_at = if_not_exists(flagged_at, :ts)",
                ConditionExpression="review_status = :none",
                ExpressionAttributeValues={":p": PENDING_REVIEW, ":none": NOT_REQUIRED, ":ts": ts},
            )
            logger.warning("Session %s/%s reached score 0 -> PENDING_REVIEW", exam_id, student_id)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise


def attach_recording(exam_id: str, sort_key: str, s3_key: Optional[str]) -> None:
    """Record the S3 object key (or failure) once the clip upload completes."""
    try:
        table = _get_table()
        if s3_key:
            table.update_item(
                Key={"exam_id": exam_id, "sort_key": sort_key},
                UpdateExpression="SET s3_object_key = :k, recording_status = :s",
                ExpressionAttributeValues={":k": s3_key, ":s": "READY"},
            )
        else:
            table.update_item(
                Key={"exam_id": exam_id, "sort_key": sort_key},
                UpdateExpression="SET recording_status = :s",
                ExpressionAttributeValues={":s": "FAILED"},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not attach recording to event: %s", exc)


async def log_event(
    exam_id: str,
    student_id: str,
    warning_type: str,
    sanity_score: int,
    session_id: str = "default",
    warning_count: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Async wrapper — runs the boto3 calls in a thread so the event loop stays free."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, create_event, exam_id, student_id, warning_type, sanity_score, session_id, warning_count
    )


async def attach_recording_async(exam_id: str, sort_key: str, s3_key: Optional[str]) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, attach_recording, exam_id, sort_key, s3_key)


# ---------------------------------------------------------------------------
# Reads / mentor review (called from the REST API — these raise on failure)
# ---------------------------------------------------------------------------

def _query_exam(exam_id: str, *, begins_with: Optional[str] = None) -> List[Dict[str, Any]]:
    from boto3.dynamodb.conditions import Key

    cond = Key("exam_id").eq(exam_id)
    if begins_with:
        cond = cond & Key("sort_key").begins_with(begins_with)
    kwargs: Dict[str, Any] = {"KeyConditionExpression": cond}
    items: List[Dict[str, Any]] = []
    table = _get_table()
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return [_clean(i) for i in items]
        kwargs["ExclusiveStartKey"] = last


def _events_for_exam(exam_id: str) -> List[Dict[str, Any]]:
    return [i for i in _query_exam(exam_id) if i.get("event_type") == "WARNING"]


def list_events(exam_id: str, student_id: str) -> List[Dict[str, Any]]:
    """Warning events for one student in one exam, oldest first."""
    rows = [e for e in _events_for_exam(exam_id) if e.get("student_id") == student_id]
    return sorted(rows, key=lambda e: e["timestamp"])


def get_event(exam_id: str, event_id: str) -> Optional[Dict[str, Any]]:
    for e in _events_for_exam(exam_id):
        if e.get("event_id") == event_id:
            return e
    return None


def get_session(exam_id: str, student_id: str) -> Optional[Dict[str, Any]]:
    resp = _get_table().get_item(Key={"exam_id": exam_id, "sort_key": f"{SESSION_PREFIX}{student_id}"})
    item = resp.get("Item")
    return _clean(item) if item else None


def list_sessions(exam_id: str) -> List[Dict[str, Any]]:
    """Session-review records for every student in an exam (pending ones first)."""
    rows = _query_exam(exam_id, begins_with=SESSION_PREFIX)
    order = {PENDING_REVIEW: 0, CONFIRMED_VIOLATION: 1, CLEARED: 2, NOT_REQUIRED: 3}
    return sorted(rows, key=lambda r: (order.get(r.get("review_status"), 9), r.get("student_id", "")))


def set_review(
    exam_id: str,
    event: Dict[str, Any],
    decision: str,
    reviewer_uid: str,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Persist a mentor's manual decision on the event AND on the student's session.
    decision must be CLEARED or CONFIRMED_VIOLATION.
    """
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
    ts = _now()
    values = {
        ":d": decision, ":by": reviewer_uid, ":at": ts, ":notes": notes or "",
    }
    expr = (
        "SET review_status = :d, mentor_decision = :d, "
        "reviewed_by = :by, reviewed_at = :at, mentor_notes = :notes"
    )
    table = _get_table()
    table.update_item(
        Key={"exam_id": exam_id, "sort_key": event["sort_key"]},
        UpdateExpression=expr, ExpressionAttributeValues=values,
    )
    table.update_item(
        Key={"exam_id": exam_id, "sort_key": f"{SESSION_PREFIX}{event['student_id']}"},
        UpdateExpression=expr + ", student_id = :sid",
        ExpressionAttributeValues={**values, ":sid": event["student_id"]},
    )
    return get_session(exam_id, event["student_id"]) or {}
