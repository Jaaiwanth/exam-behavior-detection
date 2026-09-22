"""
feature_extractor.py — Phase 3: Feature Engineering
====================================================

Converts per-frame MediaPipe landmark data (FrameLandmarks) into a
flat normalised feature vector ready for temporal modelling (LSTM).

Feature groups (total: ~60 scalar features per frame):
───────────────────────────────────────────────────────
 1. Head pose          (3)  — yaw, pitch, roll in degrees [-180, +180]
 2. Eye geometry       (4)  — left/right eye aspect ratios + gaze direction
 3. Mouth geometry     (1)  — mouth openness (chin-to-mouth dist, normed)
 4. Face-hand dist     (4)  — L/R hand index-tip & palm-center → nose, normed by face size
 5. Hand pose          (6)  — left/right wrist x, wrist y, hand-center x, hand-center y
 6. Finger curl        (5)  — right hand curl per finger (0=extended, 1=curled)
 7. Hand velocity      (4)  — Δ(wrist_x, wrist_y) for L/R from previous frame
 8. Head velocity      (3)  — Δ(yaw, pitch, roll) from previous frame
 9. Pose geometry      (6)  — shoulder width, elbow angles L/R, wrist heights L/R, torso angle
10. Detection flags    (4)  — face/L-hand/R-hand/pose detected (0 or 1)

All spatial coordinates are normalised to [0, 1] by image dimensions.
All inter-point distances are normalised by inter-ocular distance (IOD)
so the features are scale-invariant across camera distances.
Velocity features are zeroed for the first frame of each video.
Missing detections produce zeros for the corresponding feature group.

Public API
----------
FEATURE_NAMES : List[str]
    Ordered list of feature names, matching the output vector.

N_FEATURES : int
    Total number of features per frame (len(FEATURE_NAMES)).

extract_frame_features(result, prev_result) -> np.ndarray
    Extract a (N_FEATURES,) float32 vector from one FrameLandmarks.
    prev_result=None zeroes velocity features.

extract_video_features(results) -> np.ndarray
    Extract (T, N_FEATURES) array for a list of FrameLandmarks.

FeatureExtractorPipeline
    Full pipeline: video path → List[FrameLandmarks] → (T, N_FEATURES).

Usage
-----
    py -3.11 src/feature_extractor.py --video dataset/movements/eye_rubbing/eye_rubbing_001.mp4

    # Or as a module:
    from src.feature_extractor import extract_video_features, N_FEATURES
    feats = extract_video_features(landmark_results)  # (T, N_FEATURES)
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
import os
from pathlib import Path
from typing import List, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Resolve project root so this script works standalone (py -3.11 src/...) 
# and as an imported module (from src.feature_extractor import ...)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.mediapipe_processor import (
    FrameLandmarks,
    FaceResult,
    HandResult,
    PoseResult,
)

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
# Feature name registry (must stay in sync with the extractor logic below)
# ---------------------------------------------------------------------------

FEATURE_NAMES: List[str] = [
    # 1. Head pose (3)
    "face_yaw",
    "face_pitch",
    "face_roll",

    # 2. Eye geometry (4)
    "left_eye_ar",           # eye aspect ratio (openness)
    "right_eye_ar",
    "gaze_x",                # horizontal gaze direction (-1 left … +1 right)
    "gaze_y",                # vertical gaze direction   (-1 up  … +1 down)

    # 3. Mouth geometry (1)
    "mouth_open",            # mouth openness normalised by IOD

    # 4. Face–hand proximity (4)
    "lhand_index_to_nose",   # distance from left index tip to nose, / IOD
    "rhand_index_to_nose",   # distance from right index tip to nose, / IOD
    "lhand_palm_to_nose",    # distance from left palm center to nose, / IOD
    "rhand_palm_to_nose",    # distance from right palm center to nose, / IOD

    # 5. Hand pose — absolute position (4)
    "lwrist_x",
    "lwrist_y",
    "rwrist_x",
    "rwrist_y",

    # 6. Finger curl — right hand (5)
    "rcurl_thumb",
    "rcurl_index",
    "rcurl_middle",
    "rcurl_ring",
    "rcurl_pinky",

    # 7. Hand velocity (4) — Δ from previous frame
    "dlwrist_x",
    "dlwrist_y",
    "drwrist_x",
    "drwrist_y",

    # 8. Head velocity (3) — Δ from previous frame
    "dyaw",
    "dpitch",
    "droll",

    # 9. Pose geometry (6)
    "shoulder_width",        # |left_shoulder - right_shoulder| / IOD
    "left_elbow_angle",      # angle at left elbow (degrees)
    "right_elbow_angle",     # angle at right elbow (degrees)
    "lwrist_height",         # left wrist y (normalised image space; 0=top)
    "rwrist_height",         # right wrist y
    "torso_angle",           # angle of shoulder line to horizontal (degrees)

    # 10. Detection flags (4)
    "face_detected",
    "lhand_detected",
    "rhand_detected",
    "pose_detected",
]

N_FEATURES: int = len(FEATURE_NAMES)   # must equal 38


# ---------------------------------------------------------------------------
# Eye Aspect Ratio (EAR)
# Adapted from Soukupová & Čech (2016). Normalised-coordinate version.
# ---------------------------------------------------------------------------

# Indices within the 16-point eye landmark groups used in mediapipe_processor
# We only use 6 of the 16 to compute a stable EAR.
#   Vertical:   lm[1]–lm[5], lm[2]–lm[4]
#   Horizontal: lm[0]–lm[8]  (approximately)
# Since the indices vary per eye, we use face mesh indices directly.

# FaceLandmarker 478-point mesh — eye pairs used for EAR
_LEFT_EYE_EAR_INDICES  = (362, 385, 387, 263, 373, 380)  # P1–P6 clockwise
_RIGHT_EYE_EAR_INDICES = (33,  160, 158, 133, 153, 144)  # P1–P6 clockwise


def _ear(p1, p2, p3, p4, p5, p6) -> float:
    """
    Eye Aspect Ratio from 6 landmark points (normalised xy).

    EAR = (|P2–P6| + |P3–P5|) / (2 * |P1–P4|)

    Typical range: ~0.0 (fully closed) to ~0.3 (wide open).
    """
    v1 = np.linalg.norm(p2 - p6)
    v2 = np.linalg.norm(p3 - p5)
    h  = np.linalg.norm(p1 - p4)
    if h < 1e-6:
        return 0.0
    return float((v1 + v2) / (2.0 * h))


def _compute_ear(face: FaceResult, eye_indices: tuple) -> float:
    """Return EAR for one eye, or 0.0 if landmarks unavailable."""
    lm = face.landmarks
    if lm is None:
        return 0.0
    n = len(lm)
    pts = []
    for idx in eye_indices:
        if idx >= n:
            return 0.0
        pts.append(lm[idx, :2])
    return _ear(*pts)


# ---------------------------------------------------------------------------
# Inter-ocular distance (IOD) — scale normalisation
# ---------------------------------------------------------------------------

def _iod(face: FaceResult) -> float:
    """
    Return inter-ocular distance in normalised image space.
    Falls back to a safe small constant if centres are unavailable.
    """
    if face.left_eye_center is None or face.right_eye_center is None:
        return 1e-2  # fallback: ~1% of image width
    dist = float(np.linalg.norm(face.left_eye_center - face.right_eye_center))
    return max(dist, 1e-3)


# ---------------------------------------------------------------------------
# Finger curl
# ---------------------------------------------------------------------------

# Each finger: (MCP index, PIP index, DIP index, TIP index) in the 21-pt hand
_FINGER_JOINTS = {
    "thumb":  (2,  3,  4,  4),   # thumb uses CMC→MCP→IP→TIP
    "index":  (5,  6,  7,  8),
    "middle": (9,  10, 11, 12),
    "ring":   (13, 14, 15, 16),
    "pinky":  (17, 18, 19, 20),
}


def _finger_curl(lm: np.ndarray, mcp: int, pip: int, dip: int, tip: int) -> float:
    """
    Estimate finger curl as the normalised angle at the PIP joint.

    Returns 0.0 (extended) to 1.0 (fully curled).
    Uses dot-product of the two bone vectors meeting at PIP.
    """
    v1 = lm[mcp, :2] - lm[pip, :2]
    v2 = lm[tip, :2] - lm[pip, :2]  # approximate: uses tip instead of DIP
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cos_angle = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    angle_deg = math.degrees(math.acos(cos_angle))  # 0°=straight, 180°=full curl
    return float(np.clip(angle_deg / 180.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Pose angle helpers
# ---------------------------------------------------------------------------

def _angle_3pts(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """
    Angle at vertex *b* formed by points a–b–c, in degrees [0, 180].
    Returns 0.0 if any vector is degenerate.
    """
    v1, v2 = a - b, c - b
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cos_a = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return float(math.degrees(math.acos(cos_a)))


def _dist(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> float:
    """Euclidean distance between two optional 2-D points, or 0.0 if missing."""
    if a is None or b is None:
        return 0.0
    return float(np.linalg.norm(a - b))


# ---------------------------------------------------------------------------
# Per-frame feature extraction
# ---------------------------------------------------------------------------

def extract_frame_features(
    result: FrameLandmarks,
    prev_result: Optional[FrameLandmarks] = None,
) -> np.ndarray:
    """
    Extract a (N_FEATURES,) float32 feature vector from one FrameLandmarks.

    Parameters
    ----------
    result:
        Current frame landmarks from LandmarkProcessor.process_frame().
    prev_result:
        Previous frame landmarks for velocity features. Pass None (or the
        same result) to zero velocity features (e.g. first frame of video).

    Returns
    -------
    np.ndarray of shape (N_FEATURES,) and dtype float32.
    """
    face  = result.face
    lh    = result.left_hand
    rh    = result.right_hand
    pose  = result.pose

    prev_face = prev_result.face  if prev_result is not None else None
    prev_lh   = prev_result.left_hand  if prev_result is not None else None
    prev_rh   = prev_result.right_hand if prev_result is not None else None

    iod = _iod(face)

    feat: List[float] = []

    # ------------------------------------------------------------------
    # 1. Head pose  (3)
    # ------------------------------------------------------------------
    if face.detected:
        # Clamp to guard against solvePnP 180° flip artefacts on extreme angles
        yaw_c   = float(np.clip(face.yaw,   -90.0,  90.0))
        pitch_c = float(np.clip(face.pitch, -90.0,  90.0))
        roll_c  = float(np.clip(face.roll,  -45.0,  45.0))
        feat += [yaw_c, pitch_c, roll_c]
    else:
        feat += [0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # 2. Eye geometry  (4)
    # ------------------------------------------------------------------
    if face.detected and face.landmarks is not None:
        left_ear  = _compute_ear(face, _LEFT_EYE_EAR_INDICES)
        right_ear = _compute_ear(face, _RIGHT_EYE_EAR_INDICES)

        # Gaze direction: displacement of eye midpoint from face center
        # If the gaze is right, midpoint is right of center → gaze_x > 0
        if (face.left_eye_center is not None
                and face.right_eye_center is not None
                and face.face_center is not None):
            eye_mid = (face.left_eye_center + face.right_eye_center) / 2.0
            gaze = (eye_mid - face.face_center) / iod
            gaze_x = float(np.clip(gaze[0], -1.0, 1.0))
            gaze_y = float(np.clip(gaze[1], -1.0, 1.0))
        else:
            gaze_x, gaze_y = 0.0, 0.0

        feat += [left_ear, right_ear, gaze_x, gaze_y]
    else:
        feat += [0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # 3. Mouth openness  (1)
    # ------------------------------------------------------------------
    if face.detected and face.landmarks is not None:
        lm = face.landmarks
        n = len(lm)
        if 13 < n and 14 < n:
            mouth_h = float(np.linalg.norm(lm[13, :2] - lm[14, :2]))
            feat.append(mouth_h / iod)
        else:
            feat.append(0.0)
    else:
        feat.append(0.0)

    # ------------------------------------------------------------------
    # 4. Face–hand proximity  (4)
    # ------------------------------------------------------------------
    nose = face.nose_tip if face.detected else None

    lh_index_to_nose = _dist(lh.index_tip, nose)  / iod if nose is not None else 0.0
    rh_index_to_nose = _dist(rh.index_tip, nose)  / iod if nose is not None else 0.0
    lh_palm_to_nose  = _dist(lh.hand_center, nose) / iod if nose is not None else 0.0
    rh_palm_to_nose  = _dist(rh.hand_center, nose) / iod if nose is not None else 0.0

    feat += [lh_index_to_nose, rh_index_to_nose, lh_palm_to_nose, rh_palm_to_nose]

    # ------------------------------------------------------------------
    # 5. Hand pose — wrist positions  (4)
    # ------------------------------------------------------------------
    lwrist = lh.wrist if lh.detected else None
    rwrist = rh.wrist if rh.detected else None

    feat += [
        float(lwrist[0]) if lwrist is not None else 0.0,
        float(lwrist[1]) if lwrist is not None else 0.0,
        float(rwrist[0]) if rwrist is not None else 0.0,
        float(rwrist[1]) if rwrist is not None else 0.0,
    ]

    # ------------------------------------------------------------------
    # 6. Finger curl — right hand  (5)
    # ------------------------------------------------------------------
    if rh.detected and rh.landmarks is not None:
        rlm = rh.landmarks
        curls = []
        for name, (mcp, pip, dip, tip) in _FINGER_JOINTS.items():
            curls.append(_finger_curl(rlm, mcp, pip, dip, tip))
        feat += curls
    else:
        feat += [0.0, 0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # 7. Hand velocity  (4)
    # ------------------------------------------------------------------
    prev_lwrist = (prev_lh.wrist if prev_lh is not None and prev_lh.detected else None)
    prev_rwrist = (prev_rh.wrist if prev_rh is not None and prev_rh.detected else None)

    if lwrist is not None and prev_lwrist is not None:
        dlw = lwrist - prev_lwrist
        feat += [float(dlw[0]), float(dlw[1])]
    else:
        feat += [0.0, 0.0]

    if rwrist is not None and prev_rwrist is not None:
        drw = rwrist - prev_rwrist
        feat += [float(drw[0]), float(drw[1])]
    else:
        feat += [0.0, 0.0]

    # ------------------------------------------------------------------
    # 8. Head velocity  (3)
    # ------------------------------------------------------------------
    if face.detected and prev_face is not None and prev_face.detected:
        # Clamp to ±30°/frame to suppress solvePnP flip spikes
        dyaw_v   = float(np.clip(face.yaw   - prev_face.yaw,   -30.0, 30.0))
        dpitch_v = float(np.clip(face.pitch - prev_face.pitch, -30.0, 30.0))
        droll_v  = float(np.clip(face.roll  - prev_face.roll,  -30.0, 30.0))
        feat += [dyaw_v, dpitch_v, droll_v]
    else:
        feat += [0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # 9. Pose geometry  (6)
    # ------------------------------------------------------------------
    if pose.detected:
        ls = pose.left_shoulder
        rs = pose.right_shoulder
        le = pose.left_elbow
        re = pose.right_elbow
        lw_pose = pose.left_wrist
        rw_pose = pose.right_wrist

        # Shoulder width
        shoulder_w = _dist(ls, rs) / iod

        # Elbow angles
        left_elbow_ang  = _angle_3pts(ls, le, lw_pose) if (ls is not None and le is not None and lw_pose is not None) else 0.0
        right_elbow_ang = _angle_3pts(rs, re, rw_pose) if (rs is not None and re is not None and rw_pose is not None) else 0.0

        # Wrist heights (y-coordinate; 0=top of image, 1=bottom)
        lwrist_h = float(lw_pose[1]) if lw_pose is not None else 0.0
        rwrist_h = float(rw_pose[1]) if rw_pose is not None else 0.0

        # Torso angle: angle of shoulder line to horizontal
        if ls is not None and rs is not None:
            dx = float(rs[0] - ls[0])
            dy = float(rs[1] - ls[1])
            torso_ang = float(math.degrees(math.atan2(dy, dx)))
        else:
            torso_ang = 0.0

        feat += [shoulder_w, left_elbow_ang, right_elbow_ang, lwrist_h, rwrist_h, torso_ang]
    else:
        feat += [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    # ------------------------------------------------------------------
    # 10. Detection flags  (4)
    # ------------------------------------------------------------------
    feat += [
        float(face.detected),
        float(lh.detected),
        float(rh.detected),
        float(pose.detected),
    ]

    # ------------------------------------------------------------------
    # Sanity check
    # ------------------------------------------------------------------
    assert len(feat) == N_FEATURES, (
        f"Feature vector length mismatch: expected {N_FEATURES}, got {len(feat)}"
    )

    return np.array(feat, dtype=np.float32)


# ---------------------------------------------------------------------------
# Video-level feature matrix
# ---------------------------------------------------------------------------

def extract_video_features(
    results: List[FrameLandmarks],
) -> np.ndarray:
    """
    Extract a (T, N_FEATURES) float32 feature matrix from a list of
    FrameLandmarks (one per frame, in chronological order).

    The first frame has zeroed velocity features (no previous frame).

    Parameters
    ----------
    results:
        List of FrameLandmarks from LandmarkProcessor.process_video().

    Returns
    -------
    np.ndarray of shape (T, N_FEATURES) and dtype float32.
    """
    if not results:
        return np.zeros((0, N_FEATURES), dtype=np.float32)

    frames = []
    for i, result in enumerate(results):
        prev = results[i - 1] if i > 0 else None
        frames.append(extract_frame_features(result, prev))

    return np.stack(frames, axis=0)  # (T, N_FEATURES)


# ---------------------------------------------------------------------------
# Full pipeline: video → feature matrix
# ---------------------------------------------------------------------------

class FeatureExtractorPipeline:
    """
    Convenience wrapper that runs the full Phase 2 + Phase 3 pipeline:
        video path → LandmarkProcessor → FrameLandmarks → feature matrix.

    Parameters
    ----------
    face_model, hand_model, pose_model:
        Paths to the .task model files (download with setup_models.py).

    Example
    -------
    >>> from src.feature_extractor import FeatureExtractorPipeline
    >>> pipeline = FeatureExtractorPipeline()
    >>> feats = pipeline.run("dataset/movements/eye_rubbing/eye_rubbing_001.mp4")
    >>> print(feats.shape)   # e.g. (150, 38)
    """

    def __init__(
        self,
        face_model: str | Path = "models/face_landmarker.task",
        hand_model: str | Path = "models/hand_landmarker.task",
        pose_model: str | Path = "models/pose_landmarker.task",
    ) -> None:
        from src.mediapipe_processor import LandmarkProcessor
        self._lp_kwargs = dict(
            face_model_path=face_model,
            hand_model_path=hand_model,
            pose_model_path=pose_model,
        )

    def run(
        self,
        video_path: str | Path,
        max_frames: Optional[int] = None,
    ) -> np.ndarray:
        """
        Run the full pipeline on one video.

        Returns (T, N_FEATURES) float32 array.
        """
        from src.mediapipe_processor import LandmarkProcessor

        video_path = Path(video_path)
        logger.info("Extracting features: %s", video_path.name)

        with LandmarkProcessor(**self._lp_kwargs) as proc:
            results = proc.process_video(video_path, max_frames=max_frames)

        feats = extract_video_features(results)
        logger.info("  → shape %s | min %.3f | max %.3f",
                    feats.shape, float(feats.min()), float(feats.max()))
        return feats


# ---------------------------------------------------------------------------
# Dataset-level batch extraction
# ---------------------------------------------------------------------------

def extract_dataset_features(
    dataset_root: str | Path,
    output_dir: str | Path = "outputs/frame_features",
    max_frames_per_video: Optional[int] = None,
    overwrite: bool = False,
) -> None:
    """
    Run the full pipeline on every video in the dataset and save one
    .npy file per video in *output_dir*.

    Each .npy file has shape (T, N_FEATURES) and is named:
        <label>__<video_stem>.npy

    A companion CSV manifest is written to:
        <output_dir>/manifest.csv
    with columns: path, label, frames, n_features.

    Parameters
    ----------
    dataset_root:
        Root of the dataset tree (e.g. "dataset/").
    output_dir:
        Where to save .npy feature files (created if needed).
    max_frames_per_video:
        Cap frames per video (useful for quick tests; None = all frames).
    overwrite:
        If True, re-extract even if the output file already exists.
    """
    from src.video_reader import discover_videos, read_video_metadata
    from src.mediapipe_processor import LandmarkProcessor

    dataset_root = Path(dataset_root)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    videos = discover_videos(dataset_root)
    if not videos:
        logger.error("No videos found under: %s", dataset_root)
        return

    logger.info("Found %d videos. Starting feature extraction...", len(videos))

    manifest_rows = []

    # One LandmarkProcessor for the whole dataset run
    with LandmarkProcessor() as proc:
        for video_path in videos:
            label = video_path.parent.name
            out_name = f"{label}__{video_path.stem}.npy"
            out_path = output_dir / out_name

            if out_path.exists() and not overwrite:
                logger.info("  Skipping (exists): %s", out_name)
                # Still record in manifest
                feats = np.load(out_path)
                manifest_rows.append(
                    [str(out_path), label, feats.shape[0], feats.shape[1]]
                )
                continue

            try:
                results = proc.process_video(video_path, max_frames=max_frames_per_video)
                feats = extract_video_features(results)
                np.save(out_path, feats)
                manifest_rows.append(
                    [str(out_path), label, feats.shape[0], feats.shape[1]]
                )
                logger.info("  %s: %s → %s", label, video_path.name, feats.shape)
            except Exception as exc:  # noqa: BLE001
                logger.error("  FAILED %s: %s", video_path.name, exc)

    # Write manifest CSV
    import csv
    manifest_path = output_dir / "manifest.csv"
    with open(manifest_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "label", "frames", "n_features"])
        writer.writerows(manifest_rows)

    logger.info("Feature extraction complete.")
    logger.info("  Files: %d | Manifest: %s", len(manifest_rows), manifest_path)

    # Print per-label summary
    label_counts: dict[str, int] = {}
    for row in manifest_rows:
        label_counts[row[1]] = label_counts.get(row[1], 0) + 1
    logger.info("  Per-label video counts:")
    for label, count in sorted(label_counts.items()):
        logger.info("    %-30s: %d", label, count)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Phase 3 — Feature extraction.\n"
            "  --video : single video → prints feature summary\n"
            "  --dataset: batch extract whole dataset → outputs/frame_features/"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--video",   default=None, help="Single video path.")
    p.add_argument("--dataset", default=None, help="Dataset root directory.")
    p.add_argument("--output",  default="outputs/frame_features",
                   help="Output directory for batch mode (default: outputs/frame_features).")
    p.add_argument("--max-frames", type=int, default=None,
                   help="Cap frames per video (for quick tests).")
    p.add_argument("--overwrite", action="store_true",
                   help="Re-extract even if output file exists.")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.video is None and args.dataset is None:
        print("Specify --video <path> or --dataset <root>. Use --help for details.")
        raise SystemExit(1)

    if args.video:
        # Single-video mode: print feature summary
        video_path = Path(args.video)
        if not video_path.exists():
            logger.error("Video not found: %s", video_path)
            raise SystemExit(1)

        pipeline = FeatureExtractorPipeline()
        feats = pipeline.run(video_path, max_frames=args.max_frames)

        print(f"\n{'='*60}")
        print(f"Video:   {video_path.name}")
        print(f"Frames:  {feats.shape[0]}")
        print(f"Features:{feats.shape[1]}  ({N_FEATURES} expected)")
        print(f"{'='*60}")
        print(f"\n{'Feature':<25}  {'Mean':>8}  {'Std':>8}  {'Min':>8}  {'Max':>8}")
        print("-" * 65)
        for i, name in enumerate(FEATURE_NAMES):
            col = feats[:, i]
            print(f"  {name:<23}  {col.mean():>8.4f}  {col.std():>8.4f}"
                  f"  {col.min():>8.4f}  {col.max():>8.4f}")
        print()

    elif args.dataset:
        # Batch mode
        extract_dataset_features(
            dataset_root=args.dataset,
            output_dir=args.output,
            max_frames_per_video=args.max_frames,
            overwrite=args.overwrite,
        )


if __name__ == "__main__":
    main()
