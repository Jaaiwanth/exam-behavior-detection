"""
face_verifier.py — Face Identity Verification (dlib 20.0 direct API)
=====================================================================

Bypasses the face_recognition package entirely to avoid its dlib 19.x ABI
incompatibility with dlib 20.0. Calls dlib directly for:
    - Face detection (HOG frontal detector)
    - 68-point landmark prediction (shape_predictor_68)
    - 128-d face embedding (face_recognition_model_v1)

Model files are sourced from the installed face_recognition_models package
(already included when face-recognition was pip-installed).

Usage:
    verifier = FaceVerifier()
    ok = verifier.enroll(list_of_bgr_frames)  # during calibration
    result = verifier.verify(bgr_frame)        # each monitoring frame
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional imports — graceful fallback if not installed
# ---------------------------------------------------------------------------

try:
    import dlib as _dlib
    import face_recognition_models as _frm

    _detector  = _dlib.get_frontal_face_detector()
    _predictor = _dlib.shape_predictor(_frm.pose_predictor_model_location())
    _face_rec  = _dlib.face_recognition_model_v1(_frm.face_recognition_model_location())

    AVAILABLE = True
    logger.info("dlib face identity module loaded (direct API, dlib 20.0 compatible).")

except Exception as _exc:
    _dlib = _frm = _detector = _predictor = _face_rec = None
    AVAILABLE = False
    logger.warning(
        "Face identity verification disabled: %s\n"
        "Install: pip install cmake dlib face-recognition",
        _exc,
    )


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    checked:        bool  = False   # False = library not available / no face
    identity_match: bool  = True    # True = same person
    distance:       float = 0.0     # lower = more similar (threshold ~0.55)
    num_faces:      int   = 0       # faces detected in this frame


# ---------------------------------------------------------------------------
# Helpers — direct dlib calls (all same dlib 20.0 ABI)
# ---------------------------------------------------------------------------

def _get_encoding(rgb: np.ndarray) -> Optional[np.ndarray]:
    """
    Return the 128-d face embedding for the largest face in *rgb*,
    or None if no face is found.

    ROOT CAUSE NOTE
    ---------------
    bgr[:, :, ::-1] produces a NON-CONTIGUOUS numpy view (strides[-1] = -1).
    Pybind11 requires C-contiguous arrays (strides[-1] = +1) for ALL C++
    overload matching — even when shape and dtype are correct. Passing a
    non-contiguous array causes every overload to be rejected with
    'incompatible function arguments', which is why both
    compute_face_descriptor() and get_face_chip() were failing despite
    seemingly matching the documented signatures.

    Fix: np.ascontiguousarray() at entry, once, before any dlib call.
    """
    # Force C-contiguous layout — this is the critical fix
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)

    dets = _detector(rgb, 1)   # upsample 1x for better small-face detection
    if not dets:
        return None
    largest = max(dets, key=lambda d: d.width() * d.height())
    shape   = _predictor(rgb, largest)
    # Signature 1: (img, full_object_detection, num_jitters, padding)
    # This was always the correct signature — only the non-contiguous array
    # was causing the rejection, not a type or ABI mismatch.
    desc    = _face_rec.compute_face_descriptor(rgb, shape, 0, 0.25)
    return np.array(desc)


def _count_faces(rgb: np.ndarray) -> int:
    rgb = np.ascontiguousarray(rgb, dtype=np.uint8)  # must be contiguous for dlib
    return len(_detector(rgb, 1))


# ---------------------------------------------------------------------------
# FaceVerifier
# ---------------------------------------------------------------------------

class FaceVerifier:
    """
    Enroll the student's face once; verify identity per frame.

    Matching uses Euclidean distance in 128-d embedding space.
    Distances ≤ MATCH_THRESHOLD (default 0.55) are considered the same person.
    """

    MATCH_THRESHOLD = 0.55

    def __init__(self) -> None:
        self._enrolled_encodings: List[np.ndarray] = []
        self._enrolled = False

    @property
    def is_enrolled(self) -> bool:
        return self._enrolled

    # ------------------------------------------------------------------

    def enroll(self, bgr_frames: List[np.ndarray]) -> bool:
        """
        Compute face embeddings from *bgr_frames* and store as reference identity.
        Returns True if at least one face was successfully enrolled.
        """
        if not AVAILABLE:
            return False

        encodings: List[np.ndarray] = []
        for bgr in bgr_frames:
            # np.ascontiguousarray is required: bgr[:,:,::-1] produces a
            # negative-stride view that pybind11 rejects for all overloads.
            rgb = np.ascontiguousarray(bgr[:, :, ::-1], dtype=np.uint8)
            enc = _get_encoding(rgb)   # ascontiguousarray also called inside, but no-op if already contiguous
            if enc is not None:
                encodings.append(enc)

        if encodings:
            self._enrolled_encodings = encodings
            self._enrolled = True
            logger.info("Identity enrolled from %d frame(s).", len(encodings))
            return True

        logger.warning("Enrollment failed — no face detected in provided frames.")
        return False

    # ------------------------------------------------------------------

    def verify(self, bgr_frame: np.ndarray) -> VerifyResult:
        """
        Compare the face in *bgr_frame* against the enrolled identity.
        Returns VerifyResult.identity_match=False if mismatch or
        multiple faces are detected.
        """
        if not AVAILABLE or not self._enrolled:
            return VerifyResult(checked=False)

        # np.ascontiguousarray: bgr[:,:,::-1] is a non-contiguous view
        rgb       = np.ascontiguousarray(bgr_frame[:, :, ::-1], dtype=np.uint8)
        num_faces = _count_faces(rgb)

        if num_faces == 0:
            return VerifyResult(checked=True, identity_match=True, num_faces=0)

        if num_faces > 1:
            return VerifyResult(checked=True, identity_match=False,
                                num_faces=num_faces, distance=1.0)

        enc = _get_encoding(rgb)
        if enc is None:
            return VerifyResult(checked=True, identity_match=True, num_faces=1)

        # Euclidean distances against all enrolled embeddings
        distances = np.linalg.norm(
            np.array(self._enrolled_encodings) - enc, axis=1
        )
        min_dist = float(np.min(distances))
        match    = min_dist <= self.MATCH_THRESHOLD

        return VerifyResult(
            checked=True,
            identity_match=match,
            distance=min_dist,
            num_faces=1,
        )

    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear enrolled identity (call before re-calibration)."""
        self._enrolled_encodings.clear()
        self._enrolled = False
        logger.debug("FaceVerifier reset.")
