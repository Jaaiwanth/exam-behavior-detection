"""
backend/monitor_session.py — Web-Compatible Exam Monitor Session
================================================================

Extracts the stateful detection logic from exam_monitor.py into a class
with a single process_frame() entry point.

Usage:
    monitor = ExamMonitor()
    result  = monitor.process_frame(bgr_numpy_array)

process_frame() returns a MonitorResult dataclass. Call .to_dict() on it
to serialise to JSON for the FastAPI WebSocket handler.

Nothing in this module touches cv2.VideoCapture, cv2.imshow, or any
GUI-related code. All three detection layers (MediaPipe, face_verifier,
object_detector) are called exactly as they were in exam_monitor.py.

The original exam_monitor.py is NOT modified.
"""

from __future__ import annotations

import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Ensure project root (student_behavior/) is on sys.path so that
# `from src.X import Y` works regardless of where uvicorn is launched from.
# ---------------------------------------------------------------------------

_BACKEND_DIR  = Path(__file__).resolve().parent          # .../backend/
_PROJECT_ROOT = _BACKEND_DIR.parent                      # .../student_behavior/
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.mediapipe_processor import LandmarkProcessor, FrameLandmarks
from src.face_verifier       import FaceVerifier
from src.object_detector     import ObjectDetector, DetectionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds — copied verbatim from exam_monitor.py
# ---------------------------------------------------------------------------

YAW_TURN_DEG        = 20.0
HAND_FACE_DIST      = 0.16

ABSENT_PENALTY_SEC  = 5.0
WARN_DURATION_SEC   = 10
FACE_ID_CONFIRM_SEC = 4.0

YOLO_TIMERS: Dict[str, float] = {
    "phone":  3.0,
    "laptop": 3.0,
    "person": 5.0,
    "book":   8.0,
}

WARNING_HOLD_SEC   = 3
SCORE_PENALTY      = 5
STARTING_SCORE     = 100
CALIB_DURATION_SEC = 4

SMOOTH_WINDOW   = 12
SMOOTH_MIN_HITS = 8
GRACE_SEC       = 1.5

YOLO_EVERY_N_FRAMES   = 5
VERIFY_EVERY_N_FRAMES = 30
ENROLL_FRAME_BUDGET   = 20


# ---------------------------------------------------------------------------
# Calibration — identical to exam_monitor.py
# ---------------------------------------------------------------------------

@dataclass
class Calibration:
    done: bool = False
    baseline_yaw: float = 0.0
    _yaw_samples: List[float] = field(default_factory=list)
    _enroll_frames: List[np.ndarray] = field(default_factory=list)

    def add(self, yaw: float, frame: np.ndarray, near_end: bool) -> None:
        self._yaw_samples.append(yaw)
        if near_end and len(self._enroll_frames) < ENROLL_FRAME_BUDGET:
            self._enroll_frames.append(frame.copy())

    def finalise(self) -> bool:
        if len(self._yaw_samples) >= 5:
            self.baseline_yaw = float(np.median(self._yaw_samples))
            self.done = True
            logger.info("Calibration done. Baseline yaw = %.1f deg", self.baseline_yaw)
            return True
        return False

    def reset(self) -> None:
        self.done = False
        self._yaw_samples.clear()
        self._enroll_frames.clear()


# ---------------------------------------------------------------------------
# ExamFlags — identical to exam_monitor.py
# ---------------------------------------------------------------------------

@dataclass
class ExamFlags:
    head_turned_left:  bool = False
    head_turned_right: bool = False
    face_absent:       bool = False
    hand_near_face:    bool = False

    identity_mismatch: bool  = False
    identity_distance: float = 0.0

    phone_visible:  bool = False
    laptop_visible: bool = False
    person_visible: bool = False
    book_visible:   bool = False

    @property
    def head_suspicious(self) -> bool:
        return self.head_turned_left or self.head_turned_right

    def active_labels(self) -> List[str]:
        out = []
        if self.head_turned_left:  out.append("HEAD TURNED LEFT")
        if self.head_turned_right: out.append("HEAD TURNED RIGHT")
        if self.face_absent:       out.append("FACE NOT VISIBLE")
        if self.identity_mismatch: out.append(f"IDENTITY MISMATCH ({self.identity_distance:.2f})")
        if self.phone_visible:     out.append("PHONE DETECTED")
        if self.laptop_visible:    out.append("LAPTOP DETECTED")
        if self.person_visible:    out.append("EXTRA PERSON")
        if self.book_visible:      out.append("BOOK / NOTEBOOK")
        if self.hand_near_face:    out.append("hand near face")
        return out

    def to_dict(self) -> dict:
        return {
            "head_turned_left":  self.head_turned_left,
            "head_turned_right": self.head_turned_right,
            "face_absent":       self.face_absent,
            "hand_near_face":    self.hand_near_face,
            "identity_mismatch": self.identity_mismatch,
            "identity_distance": round(self.identity_distance, 3),
            "phone_visible":     self.phone_visible,
            "laptop_visible":    self.laptop_visible,
            "person_visible":    self.person_visible,
            "book_visible":      self.book_visible,
        }


# ---------------------------------------------------------------------------
# detect_pose — identical to exam_monitor.py
# ---------------------------------------------------------------------------

def detect_pose(result: FrameLandmarks, calib: Calibration) -> ExamFlags:
    flags = ExamFlags()
    face  = result.face

    if not face.detected:
        flags.face_absent = True
        return flags
    if not calib.done:
        return flags

    yaw_dev = face.yaw - calib.baseline_yaw
    if yaw_dev < -YAW_TURN_DEG:
        flags.head_turned_left  = True
    elif yaw_dev > YAW_TURN_DEG:
        flags.head_turned_right = True

    if face.face_center is not None:
        fc = face.face_center
        for hand in [result.left_hand, result.right_hand]:
            if hand.detected and hand.hand_center is not None:
                if float(np.linalg.norm(hand.hand_center - fc)) < HAND_FACE_DIST:
                    flags.hand_near_face = True
                    break
    return flags


# ---------------------------------------------------------------------------
# MonitorResult — what process_frame() returns
# ---------------------------------------------------------------------------

@dataclass
class MonitorResult:
    """
    Structured result returned by ExamMonitor.process_frame().
    Call .to_dict() to serialise to JSON for WebSocket broadcast.
    """
    calibrating:    bool  = False
    calib_progress: float = 0.0

    score:    int = STARTING_SCORE
    warnings: int = 0

    flags:        dict = field(default_factory=dict)
    new_warning:  Optional[str] = None

    timers: dict = field(default_factory=lambda: {
        "head_sus_secs": 0.0,
        "absent_secs":   0.0,
        "id_sus_secs":   0.0,
        "yolo_elapsed":  {},
    })

    active_labels: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "calibrating":    self.calibrating,
            "calib_progress": round(self.calib_progress, 2),
            "score":          self.score,
            "warnings":       self.warnings,
            "flags":          self.flags,
            "new_warning":    self.new_warning,
            "timers":         self.timers,
            "active_labels":  self.active_labels,
        }


# ---------------------------------------------------------------------------
# ExamMonitor — the main class
# ---------------------------------------------------------------------------

class ExamMonitor:
    """
    Stateful exam behaviour monitor for a single student session.
    One instance per student WebSocket connection.

    Usage
    -----
    monitor = ExamMonitor()
    result  = monitor.process_frame(bgr_frame)  # call at 1-2 FPS
    monitor.recalibrate()
    monitor.reset_score()
    monitor.close()                             # release MediaPipe on disconnect
    """

    def __init__(self, warn_after: int = WARN_DURATION_SEC, penalty: int = SCORE_PENALTY) -> None:
        self._warn_after = warn_after
        self._penalty    = penalty

        self._proc     = LandmarkProcessor()
        self._verifier = FaceVerifier()
        self._detector = ObjectDetector()

        self._reset_session()
        logger.info("ExamMonitor initialised (warn_after=%ds, penalty=%d)", warn_after, penalty)

    # ------------------------------------------------------------------

    def _reset_session(self) -> None:
        self._calib       = Calibration()
        self._calib_start: Optional[float] = None

        self._score    = STARTING_SCORE
        self._warnings = 0

        self._head_sus_since:   Optional[float] = None
        self._head_clean_since: Optional[float] = None
        self._head_recent:      Deque[bool]     = deque(maxlen=SMOOTH_WINDOW)

        self._absent_since:     Optional[float] = None
        self._id_mismatch_since: Optional[float] = None

        self._yolo_obj_since:   Dict[str, Optional[float]] = {k: None for k in YOLO_TIMERS}
        self._yolo_obj_elapsed: Dict[str, float]           = {k: 0.0  for k in YOLO_TIMERS}

        self._warning_until:  Optional[float] = None
        self._warning_reason: str             = ""

        self._last_yolo:      DetectionResult = DetectionResult(available=self._detector._model is not None)
        self._last_verify_ok: bool            = True

        self._fidx = 0

    # ------------------------------------------------------------------

    def reset_score(self) -> None:
        """Reset score and warnings without re-calibrating."""
        self._score    = STARTING_SCORE
        self._warnings = 0
        self._head_sus_since = self._head_clean_since = self._absent_since = self._id_mismatch_since = None
        self._head_recent.clear()
        self._yolo_obj_since    = {k: None for k in YOLO_TIMERS}
        self._yolo_obj_elapsed  = {k: 0.0  for k in YOLO_TIMERS}
        logger.info("Score reset.")

    def restore_state(self, score: int, warnings: int) -> None:
        """
        Re-apply the server-side score after a reconnect / refresh so reconnecting
        can never reset a student's integrity score. Calibration still restarts.
        """
        self._score    = max(0, min(STARTING_SCORE, int(score)))
        self._warnings = max(0, int(warnings))
        logger.info("Session state restored (score=%d, warnings=%d).", self._score, self._warnings)

    def recalibrate(self) -> None:
        """Restart calibration and face enrollment."""
        self._calib.reset()
        self._calib_start = None
        self._verifier.reset()
        self._head_sus_since = self._head_clean_since = None
        self._head_recent.clear()
        logger.info("Recalibrating...")

    def close(self) -> None:
        """Release MediaPipe resources. Call when student disconnects."""
        self._proc.close()
        logger.info("ExamMonitor closed.")

    # ------------------------------------------------------------------

    def process_frame(self, frame_bgr: np.ndarray) -> MonitorResult:
        """
        Process one BGR frame decoded from the student browser.

        Parameters
        ----------
        frame_bgr : np.ndarray
            OpenCV-style BGR uint8 array from cv2.imdecode().

        Returns
        -------
        MonitorResult  — call .to_dict() to get a JSON-serialisable dict.
        """
        now  = time.time()
        fidx = self._fidx
        self._fidx += 1

        # ── Layer 0: MediaPipe landmarks ──────────────────────────────
        mp_result = self._proc.process_frame(frame_bgr, frame_index=fidx)

        # ── Calibration phase ─────────────────────────────────────────
        if not self._calib.done:
            if self._calib_start is None:
                self._calib_start = now

            elapsed  = now - self._calib_start
            near_end = elapsed >= (CALIB_DURATION_SEC - 2.0)

            if mp_result.face.detected:
                self._calib.add(mp_result.face.yaw, frame_bgr, near_end)

            if elapsed >= CALIB_DURATION_SEC:
                if self._calib.finalise():
                    if not self._verifier.is_enrolled:
                        ok = self._verifier.enroll(self._calib._enroll_frames)
                        if not ok:
                            logger.warning("Enrollment failed — will retry on recalibrate.")
                else:
                    logger.warning("No face during calibration — retrying.")
                    self._calib_start = None

            return MonitorResult(
                calibrating=True,
                calib_progress=min(elapsed / CALIB_DURATION_SEC, 1.0),
                score=self._score,
                warnings=self._warnings,
            )

        # ── Warning hold ──────────────────────────────────────────────
        if self._warning_until is not None:
            if now < self._warning_until:
                return MonitorResult(
                    calibrating=False,
                    score=self._score,
                    warnings=self._warnings,
                    new_warning=self._warning_reason,
                )
            self._warning_until    = None
            self._head_sus_since   = None
            self._head_clean_since = None
            self._head_recent.clear()

        # ── Layer 1: pose detection ───────────────────────────────────
        flags = detect_pose(mp_result, self._calib)

        # ── Layer 2: face identity ────────────────────────────────────
        if self._verifier.is_enrolled and fidx % VERIFY_EVERY_N_FRAMES == 0:
            vr = self._verifier.verify(frame_bgr)
            if vr.checked:
                self._last_verify_ok    = vr.identity_match
                flags.identity_mismatch = not vr.identity_match
                flags.identity_distance = vr.distance
        else:
            flags.identity_mismatch = not self._last_verify_ok

        # ── Layer 3: YOLO object detection ────────────────────────────
        if self._detector._model is not None and fidx % YOLO_EVERY_N_FRAMES == 0:
            self._last_yolo = self._detector.detect(frame_bgr)
        flags.phone_visible  = self._last_yolo.has_phone
        flags.laptop_visible = self._last_yolo.has_laptop
        flags.person_visible = self._last_yolo.has_extra_person
        flags.book_visible   = self._last_yolo.has_book

        # ── Head-turn timer ───────────────────────────────────────────
        self._head_recent.append(flags.head_suspicious)
        smoothed_turn = self._head_recent.count(True) >= SMOOTH_MIN_HITS

        if smoothed_turn:
            self._head_clean_since = None
            if self._head_sus_since is None:
                self._head_sus_since = now
            head_sus_secs = now - self._head_sus_since
        else:
            if self._head_sus_since is not None:
                if self._head_clean_since is None:
                    self._head_clean_since = now
                elif (now - self._head_clean_since) >= GRACE_SEC:
                    self._head_sus_since = self._head_clean_since = None
            head_sus_secs = (now - self._head_sus_since) if self._head_sus_since else 0.0

        # ── Face absent timer ─────────────────────────────────────────
        if flags.face_absent:
            if self._absent_since is None:
                self._absent_since = now
            absent_secs = now - self._absent_since
        else:
            self._absent_since = None
            absent_secs        = 0.0

        # ── Identity mismatch timer ───────────────────────────────────
        if flags.identity_mismatch:
            if self._id_mismatch_since is None:
                self._id_mismatch_since = now
            id_sus_secs = now - self._id_mismatch_since
        else:
            self._id_mismatch_since = None
            id_sus_secs             = 0.0

        # ── YOLO object timers ────────────────────────────────────────
        for obj in YOLO_TIMERS:
            is_present = getattr(flags, f"{obj}_visible", False)
            if is_present:
                if self._yolo_obj_since[obj] is None:
                    self._yolo_obj_since[obj] = now
                self._yolo_obj_elapsed[obj] = now - self._yolo_obj_since[obj]
            else:
                self._yolo_obj_since[obj]   = None
                self._yolo_obj_elapsed[obj] = 0.0

        # ── Trigger warnings (same priority order as exam_monitor.py) ─
        new_warning: Optional[str] = None

        def _fire(reason: str) -> None:
            nonlocal new_warning
            self._score          = max(0, self._score - self._penalty)
            self._warnings      += 1
            self._warning_until  = now + WARNING_HOLD_SEC
            self._warning_reason = reason
            new_warning          = reason
            logger.warning("WARNING #%d — %s  Score → %d", self._warnings, reason, self._score)

        if self._head_sus_since and (now - self._head_sus_since) >= self._warn_after:
            _fire("Head turned significantly to the side.")
            self._head_sus_since   = None
            self._head_clean_since = None
            self._head_recent.clear()

        elif absent_secs >= ABSENT_PENALTY_SEC:
            _fire("Face not visible for too long.")
            self._absent_since = None

        elif id_sus_secs >= FACE_ID_CONFIRM_SEC:
            _fire("Different person detected (identity mismatch).")
            self._id_mismatch_since = None

        else:
            for obj, limit in YOLO_TIMERS.items():
                if self._yolo_obj_elapsed[obj] >= limit and new_warning is None:
                    label_map = {
                        "phone":  "Mobile phone",
                        "laptop": "Laptop",
                        "person": "Extra person",
                        "book":   "Book / notebook",
                    }
                    _fire(f"{label_map.get(obj, obj)} detected in frame.")
                    self._yolo_obj_since[obj]   = None
                    self._yolo_obj_elapsed[obj] = 0.0

        # ── Build result ──────────────────────────────────────────────
        return MonitorResult(
            calibrating    = False,
            calib_progress = 1.0,
            score          = self._score,
            warnings       = self._warnings,
            flags          = flags.to_dict(),
            new_warning    = new_warning,
            timers         = {
                "head_sus_secs": round(head_sus_secs, 2),
                "absent_secs":   round(absent_secs,   2),
                "id_sus_secs":   round(id_sus_secs,   2),
                "yolo_elapsed":  {k: round(v, 2) for k, v in self._yolo_obj_elapsed.items()},
            },
            active_labels  = flags.active_labels(),
        )
