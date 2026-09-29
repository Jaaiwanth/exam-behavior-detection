"""
exam_monitor.py — Real-Time Exam Behavior Monitor
==================================================

Detection pipeline (3 layers):

    LAYER 1 — MediaPipe head-pose (existing)
        • Head turned >= 20 deg from personal baseline
        • Face absent > 5 seconds

    LAYER 2 — Face identity verification (face_recognition)
        • Enrolled during calibration
        • Mismatch => "Different person" alert

    LAYER 3 — YOLO object detection (YOLOv8n)
        • Mobile phone detected  -> 3s timer -> warning
        • Extra person in frame  -> 5s timer -> warning
        • Book / notebook        -> 8s timer -> warning
        • Laptop                 -> 3s timer -> warning

Scoring: starts at 100. Each warning -5 pts. Floor = 0.

Run:
    py -3.11 exam_monitor.py
    py -3.11 exam_monitor.py --camera 1
    py -3.11 exam_monitor.py --warn-after 10 --penalty 5

Controls:
    Q / Esc  -- quit
    R        -- reset score
    C        -- re-calibrate
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.mediapipe_processor import LandmarkProcessor, FrameLandmarks
from src.face_verifier import FaceVerifier
from src.object_detector import ObjectDetector, DetectionResult

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

YAW_TURN_DEG       = 20.0   # deg from baseline — head turned sideways
HAND_FACE_DIST     = 0.16   # norm — hand near face (soft indicator)

ABSENT_PENALTY_SEC = 5.0    # continuous seconds without face -> warning
WARN_DURATION_SEC  = 10     # head-turn seconds -> warning
FACE_ID_CONFIRM_SEC = 4.0   # seconds of identity mismatch -> warning

# YOLO violation timers (continuous seconds)
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

# Head-turn smoothing
SMOOTH_WINDOW   = 12
SMOOTH_MIN_HITS = 8
GRACE_SEC       = 1.5

# Run YOLO every N frames to save CPU
YOLO_EVERY_N_FRAMES    = 5
# Run face verification every N frames
VERIFY_EVERY_N_FRAMES  = 30
# Collect enrollment frames during last 2 s of calibration
ENROLL_FRAME_BUDGET    = 20


# ---------------------------------------------------------------------------
# Calibration
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
# Combined flags
# ---------------------------------------------------------------------------

@dataclass
class ExamFlags:
    # Layer 1 — pose
    head_turned_left:  bool = False
    head_turned_right: bool = False
    face_absent:       bool = False
    hand_near_face:    bool = False   # soft, no timer

    # Layer 2 — identity
    identity_mismatch: bool = False
    identity_distance: float = 0.0

    # Layer 3 — YOLO objects
    phone_visible:  bool = False
    laptop_visible: bool = False
    person_visible: bool = False   # extra person
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


# ---------------------------------------------------------------------------
# Detection (Layer 1 + soft flags)
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
# Drawing helpers
# ---------------------------------------------------------------------------

FONT     = cv2.FONT_HERSHEY_SIMPLEX
CLR_OK   = (60,  210,  70)
CLR_WARN = (20,   90, 240)
CLR_SCORE= (255, 215,  50)
CLR_TEXT = (225, 225, 225)
CLR_RED  = (0,   30,  220)
CLR_CALIB= (200, 200,  50)
CLR_ID   = (200, 100, 255)   # purple — identity
CLR_OBJ  = {
    "phone":  (0,   30, 220),
    "laptop": (0,   30, 220),
    "person": (0,  140, 255),
    "book":   (30, 200, 230),
}


def _put(canvas, text, org, scale, color, thick=1):
    x, y = org
    cv2.putText(canvas, text, (x+1, y+1), FONT, scale, (0,0,0), thick+2, cv2.LINE_AA)
    cv2.putText(canvas, text, (x,   y  ), FONT, scale, color,  thick,   cv2.LINE_AA)


def _fit(frame, ww, wh) -> Tuple[np.ndarray, int, int, int, int]:
    """
    Fit frame into ww x wh window preserving aspect ratio.
    Returns (display, new_w, new_h, offset_x, offset_y).
    """
    fh, fw = frame.shape[:2]
    s = min(ww/fw, wh/fh)
    nw, nh = int(fw*s), int(fh*s)
    rsz = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((wh, ww, 3), dtype=np.uint8)
    ox, oy = (ww-nw)//2, (wh-nh)//2
    out[oy:oy+nh, ox:ox+nw] = rsz
    return out, nw, nh, ox, oy


def draw_calib(canvas, elapsed, total):
    h, w = canvas.shape[:2]
    ratio = min(elapsed / total, 1.0)
    ov = canvas.copy()
    cv2.rectangle(ov, (0,0), (w, 110), (8, 8, 25), -1)
    cv2.addWeighted(ov, 0.75, canvas, 0.25, 0, canvas)
    _put(canvas, "CALIBRATING — look straight at the screen", (20, 32), 0.60, CLR_CALIB)
    _put(canvas, f"Face will be enrolled for identity check... {max(0, total-elapsed):.1f}s", (20, 58), 0.45, CLR_TEXT)
    bx, by, bw, bh = 20, 76, w-40, 12
    cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh), (40,40,40), -1)
    cv2.rectangle(canvas, (bx, by), (bx+int(bw*ratio), by+bh), CLR_CALIB, -1)
    cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh), (110,110,110), 1)


def draw_hud(canvas, flags: ExamFlags, score: int,
             head_sus_secs: float, warn_after: int,
             absent_secs: float,
             yolo_timers: Dict[str, float],
             identity_ok: bool,
             face_verifier_active: bool,
             yolo_active: bool) -> None:
    h, w = canvas.shape[:2]

    # ── Score — top right ───────────────────────────────────────────────
    stxt  = f"SCORE: {score}"
    scol  = CLR_SCORE if score > 60 else CLR_RED
    (sw, sh), _ = cv2.getTextSize(stxt, FONT, 0.9, 2)
    ov = canvas.copy()
    cv2.rectangle(ov, (w-sw-22, 4), (w-4, sh+20), (12,12,12), -1)
    cv2.addWeighted(ov, 0.65, canvas, 0.35, 0, canvas)
    _put(canvas, stxt, (w-sw-14, sh+12), 0.9, scol, thick=2)

    # ── Feature badges (top-right, below score) ─────────────────────────
    badge_y = sh + 30
    if face_verifier_active:
        id_col  = CLR_OK if identity_ok else CLR_RED
        id_txt  = "ID:OK" if identity_ok else "ID:MISMATCH"
        (bw2, bh2), _ = cv2.getTextSize(id_txt, FONT, 0.42, 1)
        bx2 = w - bw2 - 14
        cv2.rectangle(canvas, (bx2-4, badge_y-bh2-2), (w-8, badge_y+2), (20,20,20), -1)
        _put(canvas, id_txt, (bx2, badge_y), 0.42, id_col)
        badge_y += 18
    if yolo_active:
        obj_labels = flags.active_labels()
        obj_str = "OBJ:CLEAR" if not any(
            x in obj_labels for x in ["PHONE DETECTED","LAPTOP DETECTED","EXTRA PERSON","BOOK / NOTEBOOK"]
        ) else "OBJ:ALERT"
        obj_col = CLR_OK if obj_str == "OBJ:CLEAR" else CLR_WARN
        (ow, oh), _ = cv2.getTextSize(obj_str, FONT, 0.42, 1)
        ox2 = w - ow - 14
        cv2.rectangle(canvas, (ox2-4, badge_y-oh-2), (w-8, badge_y+2), (20,20,20), -1)
        _put(canvas, obj_str, (ox2, badge_y), 0.42, obj_col)

    # ── Head-turn bar — top left ─────────────────────────────────────────
    bx, by, bw, bh_bar = 10, 10, 220, 14
    ratio  = min(head_sus_secs / warn_after, 1.0) if warn_after else 0
    bcol   = (60,200,60) if ratio < 0.5 else (0,165,255) if ratio < 0.8 else CLR_RED
    cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh_bar), (35,35,35), -1)
    if ratio > 0:
        cv2.rectangle(canvas, (bx, by), (bx+int(bw*ratio), by+bh_bar), bcol, -1)
    cv2.rectangle(canvas, (bx, by), (bx+bw, by+bh_bar), (100,100,100), 1)
    _put(canvas, f"Head turn: {head_sus_secs:.1f}s / {warn_after}s",
         (bx, by+bh_bar+15), 0.40, CLR_TEXT)

    next_y = by + bh_bar + 30

    # ── Face absent bar ─────────────────────────────────────────────────
    if absent_secs > 0.3:
        ab_r  = min(absent_secs / ABSENT_PENALTY_SEC, 1.0)
        ab_c  = (0,165,255) if ab_r < 0.7 else CLR_RED
        cv2.rectangle(canvas, (bx, next_y), (bx+bw, next_y+bh_bar), (35,35,35), -1)
        cv2.rectangle(canvas, (bx, next_y), (bx+int(bw*ab_r), next_y+bh_bar), ab_c, -1)
        cv2.rectangle(canvas, (bx, next_y), (bx+bw, next_y+bh_bar), (100,100,100), 1)
        _put(canvas, f"Face absent: {absent_secs:.1f}s / {ABSENT_PENALTY_SEC:.0f}s",
             (bx, next_y+bh_bar+15), 0.40, CLR_WARN)
        next_y += bh_bar + 30

    # ── YOLO object timers ───────────────────────────────────────────────
    for obj, elapsed in yolo_timers.items():
        if elapsed < 0.1:
            continue
        limit = YOLO_TIMERS[obj]
        yr    = min(elapsed / limit, 1.0)
        yc    = (0,165,255) if yr < 0.7 else CLR_RED
        label_map = {"phone":"Phone", "laptop":"Laptop",
                     "person":"Extra Person", "book":"Book"}
        cv2.rectangle(canvas, (bx, next_y), (bx+bw, next_y+bh_bar), (35,35,35), -1)
        cv2.rectangle(canvas, (bx, next_y), (bx+int(bw*yr), next_y+bh_bar), yc, -1)
        cv2.rectangle(canvas, (bx, next_y), (bx+bw, next_y+bh_bar), (100,100,100), 1)
        _put(canvas, f"{label_map.get(obj,obj)}: {elapsed:.1f}s / {limit:.0f}s",
             (bx, next_y+bh_bar+15), 0.40, CLR_WARN)
        next_y += bh_bar + 30

    # ── Overall status ───────────────────────────────────────────────────
    any_bad = (flags.head_suspicious or flags.face_absent or
               flags.identity_mismatch or flags.phone_visible or
               flags.laptop_visible or flags.person_visible or flags.book_visible)
    if any_bad:
        _put(canvas, "!! SUSPICIOUS ACTIVITY", (bx, next_y), 0.55, CLR_WARN)
    elif flags.hand_near_face:
        _put(canvas, "~ Hand near face",       (bx, next_y), 0.50, (30,200,200))
    else:
        _put(canvas, "OK  Normal behavior",    (bx, next_y), 0.52, CLR_OK)

    # ── Active violation labels — bottom-left ────────────────────────────
    labels = [l for l in flags.active_labels() if "hand near face" not in l.lower()]
    if labels:
        base_y = h - 14 - len(labels) * 22
        for i, lbl in enumerate(labels):
            col = CLR_ID if "IDENTITY" in lbl else CLR_WARN
            _put(canvas, f"* {lbl}", (12, base_y + i*22), 0.46, col)

    # ── Hints ────────────────────────────────────────────────────────────
    hint = "Q: Quit   R: Reset   C: Recalibrate"
    (hw, _), _ = cv2.getTextSize(hint, FONT, 0.38, 1)
    _put(canvas, hint, (w-hw-8, h-8), 0.38, (120,120,120))


def draw_warning(canvas, score: int, warnings: int, reason: str) -> None:
    h, w = canvas.shape[:2]
    cx   = w // 2
    ov   = canvas.copy()
    cv2.rectangle(ov, (0,0), (w,h), (0,0,0), -1)
    cv2.addWeighted(ov, 0.70, canvas, 0.30, 0, canvas)
    cv2.rectangle(canvas, (5,5), (w-5,h-5), (0,30,220), 7)
    for text, sc, col, th, dy in [
        ("WARNING",              1.8,  CLR_RED,    3, -110),
        (reason,                 0.55, CLR_WARN,   1,  -40),
        ("Please face the screen.", 0.52, CLR_TEXT,1,    5),
        (f"-{SCORE_PENALTY} points",  0.68,(70,70,240),2, 58),
        (f"Score: {score} / {STARTING_SCORE}", 0.65, CLR_SCORE, 2, 112),
        (f"Warning #{warnings}", 0.46, (150,150,150), 1, 150),
    ]:
        (tw, _), _ = cv2.getTextSize(text, FONT, sc, th)
        _put(canvas, text, (cx - tw//2, h//2 + dy), sc, col, thick=th)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_monitor(camera_index: int, warn_after: int, penalty: int) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        logger.error("Cannot open camera %d", camera_index)
        raise SystemExit(1)

    WIN_W, WIN_H = 960, 540
    WIN_NAME = "Exam Monitor  |  Q: Quit  R: Reset  C: Recalibrate"
    cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_NAME, WIN_W, WIN_H)

    # Initialise modules
    verifier = FaceVerifier()
    detector = ObjectDetector()

    calib         = Calibration()
    calib_start: Optional[float] = None

    score    = STARTING_SCORE
    warnings = 0

    # Head-turn timer state
    head_sus_since: Optional[float] = None
    head_clean_since: Optional[float] = None
    head_recent: Deque[bool] = deque(maxlen=SMOOTH_WINDOW)

    # Face absent timer
    absent_since: Optional[float] = None

    # Face identity timer
    id_mismatch_since: Optional[float] = None

    # YOLO per-object timers {label: start_time or None}
    yolo_obj_since: Dict[str, Optional[float]] = {k: None for k in YOLO_TIMERS}
    yolo_obj_elapsed: Dict[str, float]         = {k: 0.0  for k in YOLO_TIMERS}

    # Warning state
    warning_until:  Optional[float] = None
    warning_reason  = ""

    # Last YOLO result
    last_yolo: DetectionResult = DetectionResult(available=detector._model is not None)
    last_verify_ok  = True

    fidx = 0

    with LandmarkProcessor() as proc:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now    = time.time()
            result = proc.process_frame(frame, frame_index=fidx)
            fidx  += 1

            # ── Keys ──────────────────────────────────────────────────
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                score = STARTING_SCORE; warnings = 0
                head_sus_since = head_clean_since = absent_since = id_mismatch_since = None
                head_recent.clear()
                yolo_obj_since  = {k: None for k in YOLO_TIMERS}
                yolo_obj_elapsed= {k: 0.0  for k in YOLO_TIMERS}
                logger.info("Score reset.")
            if key == ord("c"):
                calib.reset(); calib_start = None
                verifier.reset()
                head_sus_since = head_clean_since = None; head_recent.clear()
                logger.info("Recalibrating...")

            # ── Calibration ───────────────────────────────────────────
            if not calib.done:
                if calib_start is None:
                    calib_start = now
                elapsed  = now - calib_start
                near_end = elapsed >= (CALIB_DURATION_SEC - 2.0)   # last 2 s

                if result.face.detected:
                    calib.add(result.face.yaw, frame, near_end)

                if elapsed >= CALIB_DURATION_SEC:
                    if calib.finalise():
                        if not verifier.is_enrolled:
                            ok = verifier.enroll(calib._enroll_frames)
                            if not ok:
                                logger.warning("Enrollment failed. Will retry on recalibrate.")
                    else:
                        logger.warning("No face during calibration — retrying.")
                        calib_start = None
                    display, *_ = _fit(frame, WIN_W, WIN_H)
                    cv2.imshow(WIN_NAME, display)
                    continue

                display, *_ = _fit(frame, WIN_W, WIN_H)
                draw_calib(display, elapsed, CALIB_DURATION_SEC)
                cv2.imshow(WIN_NAME, display)
                continue

            # ── Warning hold ──────────────────────────────────────────
            if warning_until is not None:
                if now < warning_until:
                    display, *_ = _fit(frame, WIN_W, WIN_H)
                    draw_warning(display, score, warnings, warning_reason)
                    cv2.imshow(WIN_NAME, display)
                    continue
                warning_until = head_sus_since = head_clean_since = None
                head_recent.clear()

            # ── Layer 1: pose detection ───────────────────────────────
            flags = detect_pose(result, calib)

            # ── Layer 2: face identity (every VERIFY_EVERY_N_FRAMES) ──
            if verifier.is_enrolled and fidx % VERIFY_EVERY_N_FRAMES == 0:
                vr = verifier.verify(frame)
                if vr.checked:
                    last_verify_ok = vr.identity_match
                    flags.identity_mismatch = not vr.identity_match
                    flags.identity_distance  = vr.distance
            else:
                flags.identity_mismatch = not last_verify_ok

            # ── Layer 3: YOLO object detection (every YOLO_EVERY_N_FRAMES)
            orig_h, orig_w = frame.shape[:2]
            if detector._model is not None and fidx % YOLO_EVERY_N_FRAMES == 0:
                last_yolo = detector.detect(frame)
            flags.phone_visible  = last_yolo.has_phone
            flags.laptop_visible = last_yolo.has_laptop
            flags.person_visible = last_yolo.has_extra_person
            flags.book_visible   = last_yolo.has_book

            # ── Fit frame to window ───────────────────────────────────
            display, disp_nw, disp_nh, ox, oy = _fit(frame, WIN_W, WIN_H)

            # Draw YOLO boxes (scaled to display coords)
            ObjectDetector.draw_scaled(
                display, last_yolo,
                orig_w, orig_h,
                disp_nw, disp_nh,
                offset_x=ox, offset_y=oy,
            )

            # ── Head-turn timer ───────────────────────────────────────
            head_recent.append(flags.head_suspicious)
            smoothed_turn = head_recent.count(True) >= SMOOTH_MIN_HITS

            if smoothed_turn:
                head_clean_since = None
                if head_sus_since is None:
                    head_sus_since = now
                head_sus_secs = now - head_sus_since
            else:
                if head_sus_since is not None:
                    if head_clean_since is None:
                        head_clean_since = now
                    elif (now - head_clean_since) >= GRACE_SEC:
                        head_sus_since = head_clean_since = None
                head_sus_secs = (now - head_sus_since) if head_sus_since else 0.0

            # ── Face absent timer ────────────────────────────────────
            if flags.face_absent:
                if absent_since is None:
                    absent_since = now
                absent_secs = now - absent_since
            else:
                absent_since = None
                absent_secs  = 0.0

            # ── Identity mismatch timer ──────────────────────────────
            if flags.identity_mismatch:
                if id_mismatch_since is None:
                    id_mismatch_since = now
                id_sus_secs = now - id_mismatch_since
            else:
                id_mismatch_since = None
                id_sus_secs = 0.0

            # ── YOLO object timers ───────────────────────────────────
            for obj in YOLO_TIMERS:
                is_present = getattr(flags, f"{obj}_visible", False)
                if is_present:
                    if yolo_obj_since[obj] is None:
                        yolo_obj_since[obj] = now
                    yolo_obj_elapsed[obj] = now - yolo_obj_since[obj]
                else:
                    yolo_obj_since[obj]   = None
                    yolo_obj_elapsed[obj] = 0.0

            # ── Trigger warnings (priority order) ────────────────────
            triggered = False

            def _fire(reason: str) -> None:
                nonlocal score, warnings, warning_until, warning_reason, triggered
                score         = max(0, score - penalty)
                warnings     += 1
                warning_until = now + WARNING_HOLD_SEC
                warning_reason = reason
                triggered     = True
                logger.warning("WARNING #%d — %s  Score -> %d", warnings, reason, score)

            if head_sus_since and (now - head_sus_since) >= warn_after:
                _fire("Head turned significantly to the side.")
                head_sus_since = head_clean_since = None; head_recent.clear()

            elif absent_secs >= ABSENT_PENALTY_SEC:
                _fire("Face not visible for too long.")
                absent_since = None

            elif id_sus_secs >= FACE_ID_CONFIRM_SEC:
                _fire("Different person detected (identity mismatch).")
                id_mismatch_since = None

            else:
                for obj, limit in YOLO_TIMERS.items():
                    if yolo_obj_elapsed[obj] >= limit and not triggered:
                        label_map = {"phone":"Mobile phone","laptop":"Laptop",
                                     "person":"Extra person","book":"Book / notebook"}
                        _fire(f"{label_map.get(obj, obj)} detected in frame.")
                        yolo_obj_since[obj]   = None
                        yolo_obj_elapsed[obj] = 0.0

            if triggered:
                draw_warning(display, score, warnings, warning_reason)
                cv2.imshow(WIN_NAME, display)
                continue

            # ── Normal HUD ────────────────────────────────────────────
            draw_hud(
                display, flags, score,
                head_sus_secs, warn_after,
                absent_secs,
                yolo_obj_elapsed,
                identity_ok=last_verify_ok,
                face_verifier_active=verifier.is_enrolled,
                yolo_active=(detector._model is not None),
            )
            cv2.imshow(WIN_NAME, display)

    cap.release()
    cv2.destroyAllWindows()
    print(f"\n{'='*44}")
    print(f"  EXAM SESSION SUMMARY")
    print(f"{'='*44}")
    print(f"  Final Score  : {score} / {STARTING_SCORE}")
    print(f"  Warnings     : {warnings}")
    print(f"  Points Lost  : {STARTING_SCORE - score}")
    print(f"{'='*44}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Exam behavior monitor — full pipeline.")
    p.add_argument("--camera",     type=int, default=0)
    p.add_argument("--warn-after", type=int, default=WARN_DURATION_SEC,
                   help=f"Head-turn seconds before penalty (default {WARN_DURATION_SEC})")
    p.add_argument("--penalty",    type=int, default=SCORE_PENALTY,
                   help=f"Points per warning (default {SCORE_PENALTY})")
    p.add_argument("--verbose",    action="store_true")
    return p.parse_args()


def main():
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    run_monitor(args.camera, args.warn_after, args.penalty)


if __name__ == "__main__":
    main()
