"""
visualize_landmarks.py — Phase 2: Landmark Visualization & Debugging
=====================================================================

Draws MediaPipe landmarks onto video frames for visual verification:
    - Face mesh key points (eyes, nose, mouth, face center)
    - Hand landmarks (21 points + skeleton per hand)
    - Pose skeleton (upper body)
    - Head pose axes (projected onto face)
    - On-frame HUD: frame index, detection status, yaw/pitch/roll

Prerequisites:
    1. Run: py -3.11 setup_models.py   (download model files once)
    2. Run with Python 3.11: py -3.11 src/visualize_landmarks.py --video <path>

Modes:
    --mode live   : show annotated frames in an OpenCV window (default)
    --mode save   : write annotated video to a file

Usage:
    py -3.11 src/visualize_landmarks.py --video dataset/movements/eye_rubbing/eye_rubbing_001.mp4
    py -3.11 src/visualize_landmarks.py --video <path> --mode save --output outputs/visualizations/annotated.mp4
    py -3.11 src/visualize_landmarks.py --video <path> --max-frames 60
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

import sys
import os as _os
# Ensure the project root is on sys.path when run as a standalone script
_project_root = str(Path(__file__).resolve().parent.parent) if "__file__" in dir() else _os.getcwd()
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.mediapipe_processor import (
    FrameLandmarks,
    FaceResult,
    HandResult,
    PoseResult,
    LandmarkProcessor,
    HAND_CONNECTIONS,
    _LEFT_EYE_INDICES,
    _RIGHT_EYE_INDICES,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette (BGR)
# ---------------------------------------------------------------------------
C_LEFT_EYE = (0, 210, 0)         # green
C_RIGHT_EYE = (0, 160, 230)      # orange
C_NOSE = (255, 80, 80)           # blue-ish
C_MOUTH = (80, 80, 255)          # red-ish
C_FACE_CENTER = (0, 255, 255)    # yellow
C_LEFT_HAND = (0, 200, 50)       # green
C_RIGHT_HAND = (50, 50, 220)     # red
C_POSE_BONE = (180, 140, 0)      # teal
C_POSE_JOINT = (255, 255, 255)   # white
C_AXIS_X = (0, 0, 255)           # red (yaw)
C_AXIS_Y = (0, 255, 0)           # green (pitch)
C_AXIS_Z = (255, 0, 0)           # blue (roll)
C_HUD_BG = (25, 25, 25)
C_HUD_TEXT = (210, 210, 210)
C_HUD_WARN = (40, 80, 220)

# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _px(norm_xy: np.ndarray, w: int, h: int) -> tuple[int, int]:
    """Normalised [0,1] → integer pixel coords."""
    return (int(norm_xy[0] * w), int(norm_xy[1] * h))


def draw_face(
    canvas: np.ndarray,
    face: FaceResult,
    draw_eyes: bool = True,
    draw_nose: bool = True,
    draw_mouth: bool = True,
    draw_center: bool = True,
    draw_pose_axes: bool = True,
) -> None:
    """Draw face landmarks and head-pose axes on *canvas* (in-place)."""
    if not face.detected:
        return

    h, w = canvas.shape[:2]
    lm = face.landmarks  # (478, 3)
    n = len(lm) if lm is not None else 0

    # Eye highlights
    if draw_eyes and lm is not None:
        for idx in _LEFT_EYE_INDICES:
            if idx < n:
                cv2.circle(canvas, _px(lm[idx], w, h), 2, C_LEFT_EYE, -1, cv2.LINE_AA)
        for idx in _RIGHT_EYE_INDICES:
            if idx < n:
                cv2.circle(canvas, _px(lm[idx], w, h), 2, C_RIGHT_EYE, -1, cv2.LINE_AA)

        if face.left_eye_center is not None:
            cv2.circle(canvas, _px(face.left_eye_center, w, h), 6, C_LEFT_EYE, 2, cv2.LINE_AA)
        if face.right_eye_center is not None:
            cv2.circle(canvas, _px(face.right_eye_center, w, h), 6, C_RIGHT_EYE, 2, cv2.LINE_AA)

    # Nose tip
    if draw_nose and face.nose_tip is not None:
        cv2.circle(canvas, _px(face.nose_tip, w, h), 5, C_NOSE, -1, cv2.LINE_AA)

    # Mouth center
    if draw_mouth and face.mouth_center is not None:
        cv2.circle(canvas, _px(face.mouth_center, w, h), 4, C_MOUTH, -1, cv2.LINE_AA)

    # Face center crosshair
    if draw_center and face.face_center is not None:
        cx, cy = _px(face.face_center, w, h)
        cv2.drawMarker(canvas, (cx, cy), C_FACE_CENTER, cv2.MARKER_CROSS, 14, 2, cv2.LINE_AA)

    # Head pose axes
    if draw_pose_axes and face.nose_tip is not None:
        _draw_pose_axes(canvas, face, w, h)


def _draw_pose_axes(
    canvas: np.ndarray, face: FaceResult, w: int, h: int, length: float = 0.08
) -> None:
    """Draw three coloured arrows showing head orientation from the nose tip."""
    yr, pr, rr = math.radians(face.yaw), math.radians(face.pitch), math.radians(face.roll)
    cy_, sy_ = math.cos(yr), math.sin(yr)
    cp, sp = math.cos(pr), math.sin(pr)
    cr, sr = math.cos(rr), math.sin(rr)

    R = np.array([
        [cy_*cr, cy_*sr*sp - sy_*cp, cy_*sr*cp + sy_*sp],
        [sy_*cr, sy_*sr*sp + cy_*cp, sy_*sr*cp - cy_*sp],
        [-sr,    cr*sp,              cr*cp              ],
    ])

    origin = _px(face.nose_tip, w, h)
    for i, colour in enumerate([C_AXIS_X, C_AXIS_Y, C_AXIS_Z]):
        axis = np.eye(3)[i] * length
        rotated = R @ axis
        end = (int(origin[0] + rotated[0] * w), int(origin[1] - rotated[1] * h))
        cv2.arrowedLine(canvas, origin, end, colour, 2, cv2.LINE_AA, tipLength=0.3)


def draw_hands(
    canvas: np.ndarray, left_hand: HandResult, right_hand: HandResult
) -> None:
    """Draw both hand skeletons on *canvas* (in-place)."""
    h, w = canvas.shape[:2]

    for hand, colour in [(left_hand, C_LEFT_HAND), (right_hand, C_RIGHT_HAND)]:
        if not hand.detected or hand.landmarks is None:
            continue

        lm = hand.landmarks  # (21, 3)

        # Skeleton bones
        for a, b in HAND_CONNECTIONS:
            cv2.line(canvas, _px(lm[a], w, h), _px(lm[b], w, h), colour, 2, cv2.LINE_AA)

        # Landmark dots (fingertips + wrist larger)
        for idx in range(21):
            r = 5 if idx in (0, 4, 8, 12, 16, 20) else 3
            cv2.circle(canvas, _px(lm[idx], w, h), r, colour, -1, cv2.LINE_AA)

        # Label key points
        for label, pt in [("W", hand.wrist), ("I", hand.index_tip)]:
            if pt is not None:
                px = _px(pt, w, h)
                cv2.putText(
                    canvas, label, (px[0] + 6, px[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, colour, 1, cv2.LINE_AA,
                )


def draw_pose(canvas: np.ndarray, pose: PoseResult) -> None:
    """Draw upper-body pose skeleton on *canvas* (in-place)."""
    if not pose.detected:
        return

    h, w = canvas.shape[:2]

    pts = {
        "nose": pose.nose,
        "left_shoulder": pose.left_shoulder,
        "right_shoulder": pose.right_shoulder,
        "left_elbow": pose.left_elbow,
        "right_elbow": pose.right_elbow,
        "left_wrist": pose.left_wrist,
        "right_wrist": pose.right_wrist,
    }

    for a, b in [
        ("left_shoulder", "right_shoulder"),
        ("left_shoulder", "left_elbow"), ("left_elbow", "left_wrist"),
        ("right_shoulder", "right_elbow"), ("right_elbow", "right_wrist"),
        ("nose", "left_shoulder"), ("nose", "right_shoulder"),
    ]:
        if pts[a] is not None and pts[b] is not None:
            cv2.line(canvas, _px(pts[a], w, h), _px(pts[b], w, h), C_POSE_BONE, 2, cv2.LINE_AA)

    for pt_norm in pts.values():
        if pt_norm is not None:
            p = _px(pt_norm, w, h)
            cv2.circle(canvas, p, 6, C_POSE_JOINT, -1, cv2.LINE_AA)
            cv2.circle(canvas, p, 6, C_POSE_BONE, 2, cv2.LINE_AA)


def draw_hud(canvas: np.ndarray, result: FrameLandmarks) -> None:
    """Draw a semi-transparent HUD panel in the top-left corner."""
    face = result.face
    lines = [
        f"Frame: {result.frame_index}",
        f"Face:  {'YES' if face.detected else 'NO '}",
        f"L-Hand:{'YES' if result.left_hand.detected else 'NO '}",
        f"R-Hand:{'YES' if result.right_hand.detected else 'NO '}",
        f"Pose:  {'YES' if result.pose.detected else 'NO '}",
    ]
    if face.detected:
        lines += [
            f"Yaw:   {face.yaw:+6.1f}",
            f"Pitch: {face.pitch:+6.1f}",
            f"Roll:  {face.roll:+6.1f}",
        ]

    font, fs, th, lh, pad = cv2.FONT_HERSHEY_SIMPLEX, 0.44, 1, 17, 6
    max_w = max(cv2.getTextSize(l, font, fs, th)[0][0] for l in lines)
    pw, ph = max_w + pad * 2, len(lines) * lh + pad * 2

    overlay = canvas.copy()
    cv2.rectangle(overlay, (0, 0), (pw, ph), C_HUD_BG, -1)
    cv2.addWeighted(overlay, 0.65, canvas, 0.35, 0, canvas)

    for i, line in enumerate(lines):
        y = pad + (i + 1) * lh - 3
        col = C_HUD_WARN if "NO" in line else C_HUD_TEXT
        cv2.putText(canvas, line, (pad, y), font, fs, col, th, cv2.LINE_AA)


def annotate_frame(frame_bgr: np.ndarray, result: FrameLandmarks) -> np.ndarray:
    """Return an annotated copy of *frame_bgr* with all landmarks drawn."""
    canvas = frame_bgr.copy()
    draw_face(canvas, result.face)
    draw_hands(canvas, result.left_hand, result.right_hand)
    draw_pose(canvas, result.pose)
    draw_hud(canvas, result)
    return canvas


# ---------------------------------------------------------------------------
# Live / save runners
# ---------------------------------------------------------------------------

def run_live(
    video_path: Path,
    proc: LandmarkProcessor,
    max_frames: Optional[int] = None,
) -> None:
    """Show annotated frames in an OpenCV window. Press 'q' to quit."""
    from src.video_reader import read_frames

    win = f"Landmarks — {video_path.name}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 540)
    logger.info("Live mode — press 'q' to quit")

    for idx, frame in read_frames(video_path, max_frames=max_frames):
        result = proc.process_frame(frame, frame_index=idx)
        cv2.imshow(win, annotate_frame(frame, result))
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cv2.destroyAllWindows()


def run_save(
    video_path: Path,
    output_path: Path,
    proc: LandmarkProcessor,
    max_frames: Optional[int] = None,
) -> None:
    """Process *video_path* and write annotated output to *output_path*."""
    from src.video_reader import read_video_metadata, read_frames

    meta = read_video_metadata(video_path)
    if not meta.readable:
        logger.error("Cannot read: %s — %s", video_path.name, meta.error)
        raise SystemExit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        meta.fps,
        (meta.width, meta.height),
    )
    logger.info("Saving annotated video → %s", output_path)

    for idx, frame in read_frames(video_path, max_frames=max_frames):
        result = proc.process_frame(frame, frame_index=idx)
        writer.write(annotate_frame(frame, result))

    writer.release()
    logger.info("Saved: %s", output_path.name)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Phase 2 — Visualize MediaPipe landmarks on a video."
    )
    p.add_argument("--video", required=True, help="Input video path.")
    p.add_argument(
        "--mode", choices=["live", "save"], default="live",
        help="'live' = show in window (default), 'save' = write to file.",
    )
    p.add_argument(
        "--output", default=None,
        help="Output file path (--mode save). Default: outputs/visualizations/<name>_annotated.mp4",
    )
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    video_path = Path(args.video)
    if not video_path.exists():
        logger.error("Video not found: %s", video_path)
        raise SystemExit(1)

    with LandmarkProcessor() as proc:
        if args.mode == "live":
            run_live(video_path, proc, args.max_frames)
        else:
            out = Path(args.output) if args.output else (
                Path("outputs/visualizations") / f"{video_path.stem}_annotated.mp4"
            )
            run_save(video_path, out, proc, args.max_frames)


if __name__ == "__main__":
    main()
