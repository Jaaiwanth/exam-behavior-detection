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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.monitor_session import ExamMonitor
from backend.dynamo_logger   import log_event, attach_recording_async
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
        # student_id → ExamMonitor instance
        self._monitors: Dict[str, ExamMonitor] = {}
        # student_id → set of faculty WebSocket connections watching them
        self._faculty_sockets: Dict[str, Set[WebSocket]] = {}

    def get_or_create_monitor(self, student_id: str) -> ExamMonitor:
        if student_id not in self._monitors:
            self._monitors[student_id] = ExamMonitor()
            logger.info("New ExamMonitor created for student=%s", student_id)
        return self._monitors[student_id]

    def remove_monitor(self, student_id: str) -> None:
        m = self._monitors.pop(student_id, None)
        if m:
            m.close()
            logger.info("ExamMonitor closed for student=%s", student_id)

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
async def recalibrate(student_id: str):
    monitor = registry._monitors.get(student_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="No active session for this student.")
    monitor.recalibrate()
    return {"status": "recalibrating"}


@app.post("/api/session/{student_id}/reset")
async def reset_score(student_id: str):
    monitor = registry._monitors.get(student_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="No active session for this student.")
    monitor.reset_score()
    return {"status": "reset"}


# ---------------------------------------------------------------------------
# Student WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/student/{student_id}")
async def student_ws(
    websocket: WebSocket,
    student_id: str,
    exam_id: str = "default",
    session_id: str = "default",
):
    # exam_id / session_id (query params) tag DynamoDB events and S3 clips per exam
    await websocket.accept()
    logger.info("Student connected: %s (exam=%s)", student_id, exam_id)

    monitor  = registry.get_or_create_monitor(student_id)
    recorder = ClipRecorder()

    async def finish_clip(event: dict, frames: list) -> None:
        """Encode + upload one warning clip, then link its S3 key to the DynamoDB event."""
        key = s3_store.recording_key(exam_id, student_id, event["event_id"])
        ok = await asyncio.get_running_loop().run_in_executor(
            None, encode_and_upload, frames, key, s3_store.upload_clip
        )
        await attach_recording_async(exam_id, event["sort_key"], key if ok else None)
        logger.info("Warning clip %s -> %s", event["event_id"][:8], "uploaded" if ok else "FAILED")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)

            msg_type = msg.get("type", "")

            # ── Control messages ──────────────────────────────────────
            if msg_type == "recalibrate":
                monitor.recalibrate()
                await websocket.send_text(json.dumps({"type": "ack", "action": "recalibrate"}))
                continue

            if msg_type == "reset":
                monitor.reset_score()
                await websocket.send_text(json.dumps({"type": "ack", "action": "reset"}))
                continue

            # ── Frame message ─────────────────────────────────────────
            if msg_type != "frame":
                continue

            b64 = msg.get("data", "")
            frame_bgr = decode_frame(b64)
            if frame_bgr is None:
                continue

            # Keep a rolling buffer; finish any warning clips whose post-roll has elapsed
            for event, frames in recorder.feed(frame_bgr):
                _spawn(finish_clip(event, frames))

            # Run the pipeline in a thread so the event loop stays responsive
            result = await asyncio.get_event_loop().run_in_executor(
                None, monitor.process_frame, frame_bgr
            )

            result_dict = result.to_dict()

            # ── Send lightweight status update to student ─────────────
            student_status = {
                "type":          "status",
                "score":         result_dict["score"],
                "warnings":      result_dict["warnings"],
                "calibrating":   result_dict["calibrating"],
                "calib_progress": result_dict["calib_progress"],
                "new_warning":   result_dict["new_warning"],
            }
            await websocket.send_text(json.dumps(student_status))

            # ── DynamoDB + S3: log only when a new warning fired ─────
            # A score of 0 only flags the session as PENDING_REVIEW (see dynamo_logger).
            # It never fails, punishes or submits the student — the mentor decides.
            if result_dict["new_warning"]:
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
        registry.remove_monitor(student_id)


# ---------------------------------------------------------------------------
# Faculty WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws/faculty/{student_id}")
async def faculty_ws(websocket: WebSocket, student_id: str):
    await websocket.accept()
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
