"""
backend/main.py — FastAPI Application
======================================

Endpoints
---------
GET  /api/quiz                  — returns the quiz questions (JSON)
GET  /api/health                — health check
POST /api/session/{student_id}/recalibrate  — restart calibration
POST /api/session/{student_id}/reset        — reset score

WebSockets
----------
WS /ws/student/{student_id}     — student sends frames, receives status
WS /ws/faculty/{student_id}     — faculty receives live feed + analysis

Student WebSocket message format (client → server):
    { "type": "frame", "data": "<base64-jpeg>" }
    { "type": "recalibrate" }
    { "type": "reset" }

Faculty WebSocket message format (server → client):
    {
      "type": "analysis",
      "student_id": "s001",
      "score": 95,
      "warnings": 1,
      "calibrating": false,
      "calib_progress": 1.0,
      "flags": { "head_turned_left": false, ... },
      "new_warning": null,
      "timers": { ... },
      "active_labels": [],
      "frame_b64": "<base64-jpeg for preview>"
    }

Student WebSocket message format (server → client):
    {
      "type": "status",
      "score": 95,
      "warnings": 1,
      "calibrating": false,
      "calib_progress": 1.0,
      "new_warning": null
    }

Run
---
    cd student_behavior/
    py -3.11 -m uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Dict, List, Optional, Set

import cv2
import numpy as np
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.monitor_session import ExamMonitor
from backend.dynamo_logger   import log_event, attach_recording_async, get_session
from backend.auth            import Caller, authenticate_ws, require_staff
from backend.recorder        import ClipRecorder, encode_and_upload
from backend.review_api      import router as review_router
from backend                 import s3_store

# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
app = FastAPI(title="Exam Proctor API", version="0.1.0")

# Allow the React dev server (localhost:5173) and any deployed CloudFront URL.
# Tighten this list in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)

# asyncio only keeps weak references to tasks — hold clip-upload tasks here until they finish
_background_tasks: set = set()


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

# ---------------------------------------------------------------------------
# Quiz data — hardcoded for the prototype.
# Replace with a DynamoDB/database read in production.
# ---------------------------------------------------------------------------

QUIZ_QUESTIONS = [
    {
        "id": 1,
        "question": "What is the time complexity of binary search?",
        "options": ["O(n)", "O(log n)", "O(n log n)", "O(1)"],
        "answer_index": 1,
    },
    {
        "id": 2,
        "question": "Which data structure uses LIFO order?",
        "options": ["Queue", "Stack", "Linked List", "Tree"],
        "answer_index": 1,
    },
    {
        "id": 3,
        "question": "What does SQL stand for?",
        "options": [
            "Structured Query Language",
            "Simple Query Language",
            "Structured Question Language",
            "Sequential Query Logic",
        ],
        "answer_index": 0,
    },
    {
        "id": 4,
        "question": "Which of the following is NOT a sorting algorithm?",
        "options": ["Merge Sort", "Quick Sort", "Binary Search", "Bubble Sort"],
        "answer_index": 2,
    },
    {
        "id": 5,
        "question": "In Python, what does `len([1, 2, 3])` return?",
        "options": ["2", "3", "4", "Error"],
        "answer_index": 1,
    },
]

EXAM_DURATION_SECONDS = 30 * 60  # 30 minutes

# ---------------------------------------------------------------------------
# Session registry — one ExamMonitor per connected student
# ---------------------------------------------------------------------------

class SessionRegistry:
    """Tracks active ExamMonitor instances and faculty WebSocket connections."""

    def __init__(self):
        # student_id → ExamMonitor instance (owned by the newest student connection)
        self._monitors: Dict[str, ExamMonitor] = {}
        # student_id → the student WebSocket that currently owns that monitor
        self._owners: Dict[str, WebSocket] = {}
        # student_id → set of faculty WebSocket connections watching them
        self._faculty_sockets: Dict[str, Set[WebSocket]] = {}

    def _new_monitor(self) -> ExamMonitor:
        return ExamMonitor()

    async def attach_monitor(self, student_id: str, ws: WebSocket) -> ExamMonitor:
        """
        Give this connection its own monitor. If the student already has a connection
        (refresh / reconnect), the older socket is closed so there is never more than one
        live session per student — and the older one cannot tear down the new monitor.
        """
        old = self._owners.get(student_id)
        if old is not None and old is not ws:
            logger.info("Replacing previous connection for student=%s", student_id)
            try:
                await old.close(code=4000)
            except Exception:
                pass
        monitor = self._new_monitor()
        self._monitors[student_id] = monitor
        self._owners[student_id] = ws
        logger.info("New ExamMonitor created for student=%s", student_id)
        return monitor

    def detach_monitor(self, student_id: str, ws: WebSocket) -> None:
        """Unregister only if this connection still owns the student's monitor."""
        if self._owners.get(student_id) is ws:
            self._owners.pop(student_id, None)
            self._monitors.pop(student_id, None)
            logger.info("ExamMonitor released for student=%s", student_id)

    def add_faculty(self, student_id: str, ws: WebSocket) -> None:
        self._faculty_sockets.setdefault(student_id, set()).add(ws)

    def remove_faculty(self, student_id: str, ws: WebSocket) -> None:
        sockets = self._faculty_sockets.get(student_id, set())
        sockets.discard(ws)

    async def broadcast_to_faculty(self, student_id: str, payload: dict) -> None:
        sockets = list(self._faculty_sockets.get(student_id, set()))
        dead = []
        msg  = json.dumps(payload)
        for ws in sockets:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._faculty_sockets.get(student_id, set()).discard(ws)


registry = SessionRegistry()


# ---------------------------------------------------------------------------
# Frame decode helper
# ---------------------------------------------------------------------------

def decode_frame(b64_string: str) -> Optional[np.ndarray]:
    """Decode a base64 JPEG string into a BGR numpy array."""
    try:
        # Strip data-URL prefix if present: "data:image/jpeg;base64,..."
        if "," in b64_string:
            b64_string = b64_string.split(",", 1)[1]
        jpg_bytes = base64.b64decode(b64_string)
        arr = np.frombuffer(jpg_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return frame
    except Exception as exc:
        logger.debug("Frame decode error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/quiz")
async def get_quiz():
    """Return quiz questions without the answer_index (hidden from student)."""
    questions_for_student = [
        {"id": q["id"], "question": q["question"], "options": q["options"]}
        for q in QUIZ_QUESTIONS
    ]
    return {
        "questions": questions_for_student,
        "duration_seconds": EXAM_DURATION_SECONDS,
        "total": len(QUIZ_QUESTIONS),
    }


@app.post("/api/session/{student_id}/recalibrate")
async def recalibrate(student_id: str, caller: Caller = Depends(require_staff)):
    # Staff only: a student must never be able to reset their own baseline.
    monitor = registry._monitors.get(student_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="No active session for this student.")
    monitor.recalibrate()
    return {"status": "recalibrating"}


@app.post("/api/session/{student_id}/reset")
async def reset_score(student_id: str, caller: Caller = Depends(require_staff)):
    # Staff only: a student must never be able to reset their own score.
    monitor = registry._monitors.get(student_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="No active session for this student.")
    monitor.reset_score()
    return {"status": "reset"}


# ---------------------------------------------------------------------------
# Student WebSocket
# ---------------------------------------------------------------------------

MAX_FRAME_MSG_BYTES = 2_000_000


@app.websocket("/ws/student/{student_id}")
async def student_ws(
    websocket: WebSocket,
    student_id: str,
    exam_id: str = "default",
    session_id: str = "default",
):
    """
    Browser -> ML pipeline. Protocol:
      1. client connects to /ws/student/{uid}?exam_id=...&session_id=...
      2. client sends {"type":"auth","token":<Firebase ID token>}; token uid must equal {uid}
      3. client sends {"type":"frame","data":<base64 JPEG>} ~2 per second
    The student only ever receives {"type":"status","calibrating":..,"calib_progress":..}.
    Score / warnings are never sent to the student browser.
    """
    await websocket.accept()

    caller = await authenticate_ws(websocket, expected_uid=student_id, roles=("student",))
    if caller is None:
        return
    logger.info("Student connected: %s (exam=%s)", student_id, exam_id)

    monitor  = await registry.attach_monitor(student_id, websocket)
    recorder = ClipRecorder()
    loop     = asyncio.get_running_loop()

    # A refresh / reconnect must not hand the student a fresh 100: restore the server-side
    # score and warning count from this exam's session record.
    last_warn_count = 0
    try:
        prior = await loop.run_in_executor(None, get_session, exam_id, student_id)
        if prior:
            monitor.restore_state(prior.get("last_score", 100), prior.get("warning_count", 0))
            last_warn_count = int(prior.get("warning_count", 0))
    except Exception as exc:
        logger.warning("Could not restore session state (%s/%s): %s", exam_id, student_id, exc)

    async def finish_clip(event: dict, frames: list) -> None:
        """Encode + upload one warning clip, then link its S3 key to the DynamoDB event."""
        key = s3_store.recording_key(exam_id, student_id, event["event_id"])
        ok = await loop.run_in_executor(None, encode_and_upload, frames, key, s3_store.upload_clip)
        await attach_recording_async(exam_id, event["sort_key"], key if ok else None)
        logger.info("Warning clip %s -> %s", event["event_id"][:8], "uploaded" if ok else "FAILED")

    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > MAX_FRAME_MSG_BYTES:
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue

            # Only frames are accepted from students. recalibrate / reset are staff-only HTTP actions.
            if msg.get("type") != "frame":
                continue

            b64 = msg.get("data", "")
            frame_bgr = decode_frame(b64)
            if frame_bgr is None:
                continue

            # Keep a rolling buffer; finish any warning clips whose post-roll has elapsed
            for event, frames in recorder.feed(frame_bgr):
                _spawn(finish_clip(event, frames))

            # Run the pipeline in a thread so the event loop stays responsive
            result = await loop.run_in_executor(None, monitor.process_frame, frame_bgr)
            result_dict = result.to_dict()

            # ── Student gets calibration progress only (no score, no warnings) ──
            await websocket.send_text(json.dumps({
                "type":           "status",
                "calibrating":    result_dict["calibrating"],
                "calib_progress": result_dict["calib_progress"],
            }))

            # ── DynamoDB + S3: log once per NEW warning ───────────────
            # The monitor repeats new_warning for every frame of its 3 s hold, so only log
            # when the cumulative warning count actually increased.
            # A score of 0 only flags the session as PENDING_REVIEW (see dynamo_logger).
            # It never fails, punishes or submits the student — the mentor decides.
            if result_dict["new_warning"] and result_dict["warnings"] > last_warn_count:
                last_warn_count = result_dict["warnings"]
                event = await log_event(
                    exam_id=exam_id,
                    student_id=student_id,
                    warning_type=result_dict["new_warning"],
                    sanity_score=result_dict["score"],
                    session_id=session_id,
                    warning_count=result_dict["warnings"],
                )
                if event:
                    recorder.arm(event)

            # ── Broadcast full analysis + frame to faculty ────────────
            faculty_payload = {
                "type":          "analysis",
                "student_id":    student_id,
                "frame_b64":     b64,            # raw JPEG — faculty previews it
                **result_dict,
            }
            await registry.broadcast_to_faculty(student_id, faculty_payload)

    except WebSocketDisconnect:
        logger.info("Student disconnected: %s", student_id)
    except Exception as exc:
        logger.error("Student WS error (%s): %s", student_id, exc)
    finally:
        for event, frames in recorder.flush():      # clips still waiting for post-roll
            _spawn(finish_clip(event, frames))
        registry.detach_monitor(student_id, websocket)
        try:
            monitor.close()
        except Exception as exc:
            logger.warning("Monitor close failed (%s): %s", student_id, exc)


# ---------------------------------------------------------------------------
# Faculty WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/faculty/{student_id}")
async def faculty_ws(websocket: WebSocket, student_id: str):
    await websocket.accept()

    # Live video and scores are for staff only (same first-message token handshake).
    caller = await authenticate_ws(websocket, expected_uid=None, roles=("mentor", "admin"))
    if caller is None:
        return
    logger.info("Faculty connected, watching student=%s", student_id)

    registry.add_faculty(student_id, websocket)

    try:
        # Keep the connection alive; faculty only receives, never sends.
        while True:
            await websocket.receive_text()   # absorb any pings
    except WebSocketDisconnect:
        logger.info("Faculty disconnected, watching student=%s", student_id)
    except Exception as exc:
        logger.error("Faculty WS error (student=%s): %s", student_id, exc)
    finally:
        registry.remove_faculty(student_id, websocket)
