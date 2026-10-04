"""
backend/review_api.py — mentor manual-review endpoints
=======================================================

All endpoints require a mentor/admin Firebase token AND ownership of the exam
(admins: any exam). Students get 403 on every route here.

    GET   /api/exams/{exam_id}/reviews                    sessions needing / having review
    GET   /api/events/{student_id}?exam_id=...            one student's warning events + session
    GET   /api/events/{event_id}/recording?exam_id=...    short-lived presigned URL
    PATCH /api/events/{event_id}/review?exam_id=...       mentor decision

A score of 0 only makes a session PENDING_REVIEW. Nothing here (or anywhere) fails,
punishes or auto-submits a student; the mentor's decision is the final verification.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend import auth, dynamo_logger as db, s3_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _dynamo_call(fn, *args):
    try:
        return fn(*args)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("DynamoDB call failed (%s): %s", getattr(fn, "__name__", fn), exc)
        raise HTTPException(status_code=502, detail="Could not read from DynamoDB.")


@router.get("/exams/{exam_id}/reviews")
def exam_reviews(exam_id: str, caller: auth.Caller = Depends(auth.require_staff)):
    """Per-student review status for an exam (PENDING_REVIEW listed first)."""
    auth.ensure_exam_access(caller, exam_id)
    return {"exam_id": exam_id, "sessions": _dynamo_call(db.list_sessions, exam_id)}


@router.get("/events/{student_id}")
def student_events(
    student_id: str,
    exam_id: str = Query(..., description="Exam the events belong to"),
    caller: auth.Caller = Depends(auth.require_staff),
):
    auth.ensure_exam_access(caller, exam_id)
    events = _dynamo_call(db.list_events, exam_id, student_id)
    session = _dynamo_call(db.get_session, exam_id, student_id)
    for e in events:
        e["has_recording"] = bool(e.get("s3_object_key"))
        e.pop("s3_object_key", None)       # internal reference — the browser never needs it
    return {"student_id": student_id, "exam_id": exam_id, "session": session, "events": events}


@router.get("/events/{event_id}/recording")
def event_recording(
    event_id: str,
    exam_id: str = Query(...),
    caller: auth.Caller = Depends(auth.require_staff),
):
    auth.ensure_exam_access(caller, exam_id)
    event = _dynamo_call(db.get_event, exam_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found for this exam.")
    key = event.get("s3_object_key")
    if not key:
        status = event.get("recording_status", "NONE")
        detail = ("Recording is still being processed." if status == "PENDING"
                  else "No recording is available for this event.")
        raise HTTPException(status_code=404, detail=detail)
    try:
        url = s3_store.presign_get(key)
    except Exception as exc:  # noqa: BLE001
        logger.error("Presign failed (%s): %s", key, exc)
        raise HTTPException(status_code=502, detail="Could not create a recording link.")
    return {"url": url, "expires_in": s3_store.PRESIGN_EXPIRES_SEC}


class ReviewBody(BaseModel):
    decision: str = Field(..., description="CLEARED or CONFIRMED_VIOLATION")
    notes: Optional[str] = Field(default="", max_length=2000)


@router.patch("/events/{event_id}/review")
def review_event(
    event_id: str,
    body: ReviewBody,
    exam_id: str = Query(...),
    caller: auth.Caller = Depends(auth.require_staff),
):
    auth.ensure_exam_access(caller, exam_id)
    if body.decision not in db.DECISIONS:
        raise HTTPException(status_code=422, detail=f"decision must be one of {sorted(db.DECISIONS)}")
    event = _dynamo_call(db.get_event, exam_id, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found for this exam.")
    session = _dynamo_call(db.set_review, exam_id, event, body.decision, caller.uid, body.notes or "")
    return {"session": session}
