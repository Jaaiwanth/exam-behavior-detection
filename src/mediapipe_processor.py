"""
mediapipe_processor.py — Phase 2: MediaPipe Landmark Extraction
================================================================

Uses the MediaPipe 1.0+ Tasks API (FaceLandmarker, HandLandmarker,
PoseLandmarker) to extract landmarks from video frames.

Before using this module, download the required model files:
    py -3.11 setup_models.py

Then run scripts with Python 3.11 (mediapipe 1.0+ does not support 3.14):
    py -3.11 src/mediapipe_processor.py --video <path>

Responsibilities:
    - Extract face mesh landmarks (478 points) including eyes, nose, mouth.
    - Estimate approximate head pose (yaw, pitch, roll) from face geometry.
    - Extract hand landmarks (21 points per hand) for left and right hands.
    - Extract upper-body pose landmarks (shoulders, elbows, wrists, etc.).
    - Return structured dataclasses for every frame.
    - Handle missing detections safely — never crash when face/hands absent.

Public API:
    LandmarkProcessor   — context-managed processor (face + hands + pose)
    FrameLandmarks      — per-frame result container
    FaceResult          — face mesh + head pose + key points
    HandResult          — single-hand landmarks + key points
    PoseResult          — upper-body pose landmarks

Usage:
    from src.mediapipe_processor import LandmarkProcessor
    from src.video_reader import read_frames

    with LandmarkProcessor() as proc:
        for idx, frame in read_frames("dataset/.../video.mp4"):
            result = proc.process_frame(frame, frame_index=idx)
            print(result.face.yaw, result.face.pitch)

Standalone:
    py -3.11 src/mediapipe_processor.py --video dataset/movements/eye_rubbing/eye_rubbing_001.mp4
"""

from __future__ import annotations

import argparse
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

try:
    import mediapipe as mp
    import mediapipe.tasks as mp_tasks
except ImportError as exc:
    raise ImportError(
        "mediapipe is required.\n"
        "Install with: py -3.11 -m pip install mediapipe\n"
        "(mediapipe requires Python 3.10–3.12)"
    ) from exc

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default model file paths
# ---------------------------------------------------------------------------

_MODELS_DIR = Path("models")
DEFAULT_FACE_MODEL = _MODELS_DIR / "face_landmarker.task"
DEFAULT_HAND_MODEL = _MODELS_DIR / "hand_landmarker.task"
DEFAULT_POSE_MODEL = _MODELS_DIR / "pose_landmarker.task"

# ---------------------------------------------------------------------------
# Key landmark indices for FaceLandmarker (478 points in Tasks API)
# ---------------------------------------------------------------------------

# 3-D face model points for solvePnP head-pose estimation (units: mm)
_FACE_3D_MODEL = np.array(
    [
        [0.0, 0.0, 0.0],       # Nose tip        — landmark 4
        [0.0, -63.6, -12.5],   # Chin            — landmark 152
        [-43.3, 32.7, -26.0],  # Left eye outer  — landmark 263
        [43.3, 32.7, -26.0],   # Right eye outer — landmark 33
        [-28.9, -28.9, -24.1], # Left mouth      — landmark 287
        [28.9, -28.9, -24.1],  # Right mouth     — landmark 57
    ],
    dtype=np.float64,
)
_POSE_LANDMARK_INDICES_2D = [4, 152, 263, 33, 287, 57]

# Eye landmark groups
_LEFT_EYE_INDICES = [
    362, 382, 381, 380, 374, 373, 390, 249,
    263, 466, 388, 387, 386, 385, 384, 398,
]
_RIGHT_EYE_INDICES = [
    33, 7, 163, 144, 145, 153, 154, 155,
    133, 173, 157, 158, 159, 160, 161, 246,
]

# Singular key landmarks
NOSE_TIP_IDX = 4
NOSE_BRIDGE_IDX = 6
CHIN_IDX = 152
LEFT_MOUTH_IDX = 61
RIGHT_MOUTH_IDX = 291
MOUTH_TOP_IDX = 13
MOUTH_BOTTOM_IDX = 14

# MediaPipe Hands key landmark indices
WRIST_IDX = 0
THUMB_TIP_IDX = 4
INDEX_TIP_IDX = 8
MIDDLE_TIP_IDX = 12
RING_TIP_IDX = 16
PINKY_TIP_IDX = 20

# MediaPipe Pose: upper-body landmark indices (PoseLandmark enum values)
_POSE_UPPER_BODY = {
    "nose": 0,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_elbow": 13,
    "right_elbow": 14,
    "left_wrist": 15,
    "right_wrist": 16,
}

# ---------------------------------------------------------------------------
# Hand connections for visualization (21 landmarks)
# ---------------------------------------------------------------------------

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # Index
    (0, 9), (9, 10), (10, 11), (11, 12),     # Middle
    (0, 13), (13, 14), (14, 15), (15, 16),   # Ring
    (0, 17), (17, 18), (18, 19), (19, 20),   # Pinky
    (5, 9), (9, 13), (13, 17),               # Palm
]

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FaceResult:
    """Extracted face data for one frame."""

    detected: bool

    # Full landmark array: shape (N, 3), normalised [0, 1].
    # N = 478 for FaceLandmarker (Tasks API with attention mesh).
    landmarks: Optional[np.ndarray] = None

    # Key 2-D points (normalised [0,1])
    face_center: Optional[np.ndarray] = None
    left_eye_center: Optional[np.ndarray] = None
    right_eye_center: Optional[np.ndarray] = None
    nose_tip: Optional[np.ndarray] = None
    nose_bridge: Optional[np.ndarray] = None
    chin: Optional[np.ndarray] = None
    mouth_center: Optional[np.ndarray] = None

    # Head pose (approximate degrees)
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0

    # Bounding box [x_min, y_min, x_max, y_max] in pixel coords
    bbox_px: Optional[np.ndarray] = None


@dataclass
class HandResult:
    """Extracted landmarks for one hand."""

    detected: bool
    handedness: str = ""  # "Left" or "Right"

    # Full landmark array: shape (21, 3), normalised [0, 1].
    landmarks: Optional[np.ndarray] = None

    # Key 2-D points (normalised [0,1])
    wrist: Optional[np.ndarray] = None
    thumb_tip: Optional[np.ndarray] = None
    index_tip: Optional[np.ndarray] = None
    middle_tip: Optional[np.ndarray] = None
    ring_tip: Optional[np.ndarray] = None
    pinky_tip: Optional[np.ndarray] = None
    hand_center: Optional[np.ndarray] = None


@dataclass
class PoseResult:
    """Extracted upper-body pose landmarks for one frame."""

    detected: bool

    # Full landmark array: shape (33, 4) — x, y, z, visibility; normalised.
    landmarks: Optional[np.ndarray] = None

    # Named upper-body points (normalised x, y)
    nose: Optional[np.ndarray] = None
    left_shoulder: Optional[np.ndarray] = None
    right_shoulder: Optional[np.ndarray] = None
    left_elbow: Optional[np.ndarray] = None
    right_elbow: Optional[np.ndarray] = None
    left_wrist: Optional[np.ndarray] = None
    right_wrist: Optional[np.ndarray] = None


@dataclass
class FrameLandmarks:
    """All landmark data for a single video frame."""

    frame_index: int
    face: FaceResult
    left_hand: HandResult
    right_hand: HandResult
    pose: PoseResult
    image_width: int = 0
    image_height: int = 0


# ---------------------------------------------------------------------------
# Head pose estimation
# ---------------------------------------------------------------------------

def _estimate_head_pose(
    landmarks_norm: np.ndarray,
    image_width: int,
    image_height: int,
) -> Tuple[float, float, float]:
    """
    Estimate approximate head pose (yaw, pitch, roll) in degrees.

    Uses OpenCV solvePnP with a standard 6-point face model and
    an assumed pinhole camera (focal length = image width).

    Returns (0.0, 0.0, 0.0) if solvePnP fails or landmarks are insufficient.
    """
    n_landmarks = len(landmarks_norm)
    for idx in _POSE_LANDMARK_INDICES_2D:
        if idx >= n_landmarks:
            return 0.0, 0.0, 0.0

    image_points = np.array(
        [
            [landmarks_norm[idx, 0] * image_width,
             landmarks_norm[idx, 1] * image_height]
            for idx in _POSE_LANDMARK_INDICES_2D
        ],
        dtype=np.float64,
    )

    focal_length = float(image_width)
    cx, cy = image_width / 2.0, image_height / 2.0
    camera_matrix = np.array(
        [[focal_length, 0, cx], [0, focal_length, cy], [0, 0, 1]],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    success, rotation_vec, _ = cv2.solvePnP(
        _FACE_3D_MODEL, image_points, camera_matrix, dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return 0.0, 0.0, 0.0

    R, _ = cv2.Rodrigues(rotation_vec)
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    if sy > 1e-6:
        roll = math.degrees(math.atan2(R[2, 1], R[2, 2]))
        pitch = math.degrees(math.atan2(-R[2, 0], sy))
        yaw = math.degrees(math.atan2(R[1, 0], R[0, 0]))
    else:
        roll = math.degrees(math.atan2(-R[1, 2], R[1, 1]))
        pitch = math.degrees(math.atan2(-R[2, 0], sy))
        yaw = 0.0

    return float(yaw), float(pitch), float(roll)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def _extract_face(face_result, image_width: int, image_height: int) -> FaceResult:
    """Parse FaceLandmarker result into FaceResult."""
    if not face_result.face_landmarks:
        return FaceResult(detected=False)

    raw_lm = face_result.face_landmarks[0]  # first detected face
    lm_array = np.array(
        [[lm.x, lm.y, lm.z] for lm in raw_lm], dtype=np.float32
    )  # (478, 3)

    n = len(lm_array)

    def _pt(idx: int) -> np.ndarray:
        return lm_array[idx, :2].copy() if idx < n else np.zeros(2, dtype=np.float32)

    # Eye centres — use only indices that exist
    valid_left = [i for i in _LEFT_EYE_INDICES if i < n]
    valid_right = [i for i in _RIGHT_EYE_INDICES if i < n]
    left_eye_center = lm_array[valid_left, :2].mean(axis=0) if valid_left else None
    right_eye_center = lm_array[valid_right, :2].mean(axis=0) if valid_right else None
    face_center = lm_array[:, :2].mean(axis=0)

    # Mouth centre
    if MOUTH_TOP_IDX < n and MOUTH_BOTTOM_IDX < n and LEFT_MOUTH_IDX < n and RIGHT_MOUTH_IDX < n:
        mouth_center = np.array(
            [
                (lm_array[LEFT_MOUTH_IDX, 0] + lm_array[RIGHT_MOUTH_IDX, 0]) / 2,
                (lm_array[MOUTH_TOP_IDX, 1] + lm_array[MOUTH_BOTTOM_IDX, 1]) / 2,
            ],
            dtype=np.float32,
        )
    else:
        mouth_center = None

    # Bounding box
    x_px = lm_array[:, 0] * image_width
    y_px = lm_array[:, 1] * image_height
    bbox_px = np.array([x_px.min(), y_px.min(), x_px.max(), y_px.max()], dtype=np.float32)

    yaw, pitch, roll = _estimate_head_pose(lm_array, image_width, image_height)

    return FaceResult(
        detected=True,
        landmarks=lm_array,
        face_center=face_center,
        left_eye_center=left_eye_center,
        right_eye_center=right_eye_center,
        nose_tip=_pt(NOSE_TIP_IDX),
        nose_bridge=_pt(NOSE_BRIDGE_IDX),
        chin=_pt(CHIN_IDX),
        mouth_center=mouth_center,
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        bbox_px=bbox_px,
    )


def _extract_hands(hand_result) -> Tuple[HandResult, HandResult]:
    """Parse HandLandmarker result into (left, right) HandResults."""
    no_hand = HandResult(detected=False)
    left_result, right_result = no_hand, no_hand

    if not hand_result.hand_landmarks:
        return left_result, right_result

    for raw_lm, handedness_list in zip(
        hand_result.hand_landmarks, hand_result.handedness
    ):
        label = handedness_list[0].display_name  # "Left" or "Right"

        lm_array = np.array(
            [[lm.x, lm.y, lm.z] for lm in raw_lm], dtype=np.float32
        )  # (21, 3)

        def _tip(idx: int) -> np.ndarray:
            return lm_array[idx, :2].copy()

        hr = HandResult(
            detected=True,
            handedness=label,
            landmarks=lm_array,
            wrist=_tip(WRIST_IDX),
            thumb_tip=_tip(THUMB_TIP_IDX),
            index_tip=_tip(INDEX_TIP_IDX),
            middle_tip=_tip(MIDDLE_TIP_IDX),
            ring_tip=_tip(RING_TIP_IDX),
            pinky_tip=_tip(PINKY_TIP_IDX),
            hand_center=lm_array[:, :2].mean(axis=0),
        )

        if label == "Left":
            left_result = hr
        else:
            right_result = hr

    return left_result, right_result


def _extract_pose(pose_result) -> PoseResult:
    """Parse PoseLandmarker result into PoseResult."""
    if not pose_result.pose_landmarks:
        return PoseResult(detected=False)

    raw_lm = pose_result.pose_landmarks[0]
    lm_array = np.array(
        [[lm.x, lm.y, lm.z, lm.visibility] for lm in raw_lm],
        dtype=np.float32,
    )  # (33, 4)

    def _pt(key: str) -> np.ndarray:
        idx = _POSE_UPPER_BODY[key]
        return lm_array[idx, :2].copy()

    return PoseResult(
        detected=True,
        landmarks=lm_array,
        nose=_pt("nose"),
        left_shoulder=_pt("left_shoulder"),
        right_shoulder=_pt("right_shoulder"),
        left_elbow=_pt("left_elbow"),
        right_elbow=_pt("right_elbow"),
        left_wrist=_pt("left_wrist"),
        right_wrist=_pt("right_wrist"),
    )


# ---------------------------------------------------------------------------
# Core processor class
# ---------------------------------------------------------------------------

class LandmarkProcessor:
    """
    Processes video frames with MediaPipe FaceLandmarker, HandLandmarker,
    and PoseLandmarker (Tasks API, mediapipe 1.0+).

    Must be used as a context manager so all resources are released properly.

    Parameters
    ----------
    face_model_path:
        Path to face_landmarker.task (download with setup_models.py).
    hand_model_path:
        Path to hand_landmarker.task.
    pose_model_path:
        Path to pose_landmarker.task.
    max_num_hands:
        Maximum hands to detect per frame (default 2).
    min_face_confidence, min_hand_confidence, min_pose_confidence:
        Minimum detection confidence thresholds.

    Example
    -------
    >>> from src.mediapipe_processor import LandmarkProcessor
    >>> from src.video_reader import read_frames
    >>> with LandmarkProcessor() as proc:
    ...     for idx, frame in read_frames("path/to/video.mp4"):
    ...         result = proc.process_frame(frame, frame_index=idx)
    ...         print(result.face.yaw)
    """

    def __init__(
        self,
        face_model_path: str | Path = DEFAULT_FACE_MODEL,
        hand_model_path: str | Path = DEFAULT_HAND_MODEL,
        pose_model_path: str | Path = DEFAULT_POSE_MODEL,
        max_num_hands: int = 2,
        min_face_confidence: float = 0.5,
        min_hand_confidence: float = 0.5,
        min_pose_confidence: float = 0.5,
    ) -> None:
        self._check_models(face_model_path, hand_model_path, pose_model_path)

        BaseOptions = mp_tasks.BaseOptions
        vision = mp_tasks.vision
        VisionRunningMode = vision.RunningMode

        # Face Landmarker
        self._face_landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(face_model_path)),
                running_mode=VisionRunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=min_face_confidence,
                min_face_presence_confidence=min_face_confidence,
                min_tracking_confidence=min_face_confidence,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
        )

        # Hand Landmarker
        self._hand_landmarker = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(hand_model_path)),
                running_mode=VisionRunningMode.VIDEO,
                num_hands=max_num_hands,
                min_hand_detection_confidence=min_hand_confidence,
                min_hand_presence_confidence=min_hand_confidence,
                min_tracking_confidence=min_hand_confidence,
            )
        )

        # Pose Landmarker
        self._pose_landmarker = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(pose_model_path)),
                running_mode=VisionRunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=min_pose_confidence,
                min_pose_presence_confidence=min_pose_confidence,
                min_tracking_confidence=min_pose_confidence,
            )
        )

        self._frame_timestamp_ms = 0
        logger.info("LandmarkProcessor initialised (face + hands + pose)")

    @staticmethod
    def _check_models(*paths) -> None:
        """Raise FileNotFoundError if any model file is missing."""
        missing = [str(p) for p in paths if not Path(p).exists()]
        if missing:
            raise FileNotFoundError(
                "Model file(s) not found:\n"
                + "\n".join(f"  {p}" for p in missing)
                + "\n\nRun: py -3.11 setup_models.py"
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "LandmarkProcessor":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        """Release all MediaPipe resources."""
        self._face_landmarker.close()
        self._hand_landmarker.close()
        self._pose_landmarker.close()
        logger.debug("LandmarkProcessor closed")

    # ------------------------------------------------------------------
    # Single-frame processing
    # ------------------------------------------------------------------

    def process_frame(
        self,
        frame_bgr: np.ndarray,
        frame_index: int = 0,
    ) -> FrameLandmarks:
        """
        Extract face, hand, and pose landmarks from a single BGR frame.

        Parameters
        ----------
        frame_bgr:
            OpenCV-style BGR uint8 array of shape (H, W, 3).
        frame_index:
            Zero-based index of this frame within its source video.

        Returns
        -------
        FrameLandmarks with all components populated.
        """
        h, w = frame_bgr.shape[:2]

        # Convert BGR -> RGB for MediaPipe
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Each frame needs a strictly increasing timestamp (milliseconds)
        self._frame_timestamp_ms = frame_index * 33  # assume ~30fps spacing

        face_res = self._face_landmarker.detect_for_video(
            mp_image, self._frame_timestamp_ms
        )
        hand_res = self._hand_landmarker.detect_for_video(
            mp_image, self._frame_timestamp_ms
        )
        pose_res = self._pose_landmarker.detect_for_video(
            mp_image, self._frame_timestamp_ms
        )

        face = _extract_face(face_res, w, h)
        left_hand, right_hand = _extract_hands(hand_res)
        pose = _extract_pose(pose_res)

        return FrameLandmarks(
            frame_index=frame_index,
            face=face,
            left_hand=left_hand,
            right_hand=right_hand,
            pose=pose,
            image_width=w,
            image_height=h,
        )

    # ------------------------------------------------------------------
    # Full-video processing
    # ------------------------------------------------------------------

    def process_video(
        self,
        video_path: str | Path,
        max_frames: Optional[int] = None,
        log_interval: int = 50,
    ) -> List[FrameLandmarks]:
        """
        Process every frame of a video and return a list of FrameLandmarks.

        Parameters
        ----------
        video_path:
            Path to the .mp4 file.
        max_frames:
            Stop after this many frames (useful for quick tests).
        log_interval:
            Log progress every N frames.

        Returns
        -------
        List of FrameLandmarks in chronological order.
        """
        import sys
        import os
        # Ensure the project root is on sys.path when running as a standalone script
        _project_root = str(Path(__file__).resolve().parent.parent)
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)
        from src.video_reader import read_frames

        video_path = Path(video_path)
        logger.info("Processing video: %s", video_path.name)

        results: List[FrameLandmarks] = []

        for idx, frame in read_frames(video_path, max_frames=max_frames):
            result = self.process_frame(frame, frame_index=idx)
            results.append(result)

            if (idx + 1) % log_interval == 0:
                logger.debug(
                    "Frame %4d  face=%s  L=%s  R=%s  pose=%s",
                    idx,
                    result.face.detected,
                    result.left_hand.detected,
                    result.right_hand.detected,
                    result.pose.detected,
                )

        n = len(results)
        if n > 0:
            face_n = sum(r.face.detected for r in results)
            lh_n = sum(r.left_hand.detected for r in results)
            rh_n = sum(r.right_hand.detected for r in results)
            pose_n = sum(r.pose.detected for r in results)
            logger.info(
                "%s | %d frames | face %d/%d | L-hand %d/%d | R-hand %d/%d | pose %d/%d",
                video_path.name, n,
                face_n, n, lh_n, n, rh_n, n, pose_n, n,
            )

        return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 2 — MediaPipe landmark extraction: process a video and report detection rates."
    )
    parser.add_argument("--video", required=True, help="Path to an .mp4 video file.")
    parser.add_argument(
        "--max-frames", type=int, default=None,
        help="Process only the first N frames (default: all).",
    )
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    video_path = Path(args.video)
    if not video_path.exists():
        logger.error("Video not found: %s", video_path)
        raise SystemExit(1)

    with LandmarkProcessor() as proc:
        results = proc.process_video(video_path, max_frames=args.max_frames)

    if not results:
        logger.warning("No frames processed.")
        return

    print("\n--- Head Pose Sample (first 10 face-detected frames) ---")
    print(f"{'Frame':>6}  {'Yaw':>8}  {'Pitch':>8}  {'Roll':>8}  Hands")
    print("-" * 50)
    shown = 0
    for r in results:
        if not r.face.detected:
            continue
        hands = []
        if r.left_hand.detected:
            hands.append("L")
        if r.right_hand.detected:
            hands.append("R")
        print(
            f"{r.frame_index:>6}  "
            f"{r.face.yaw:>7.1f}°  "
            f"{r.face.pitch:>7.1f}°  "
            f"{r.face.roll:>7.1f}°  "
            f"{'/'.join(hands) or '-'}"
        )
        shown += 1
        if shown >= 10:
            break

    n = len(results)
    print(f"\nDetection rates over {n} frames:")
    print(f"  Face:       {100*sum(r.face.detected for r in results)/n:5.1f}%")
    print(f"  Left hand:  {100*sum(r.left_hand.detected for r in results)/n:5.1f}%")
    print(f"  Right hand: {100*sum(r.right_hand.detected for r in results)/n:5.1f}%")
    print(f"  Pose:       {100*sum(r.pose.detected for r in results)/n:5.1f}%")
    print()


if __name__ == "__main__":
    main()
