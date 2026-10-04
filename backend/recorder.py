"""
backend/recorder.py — rolling frame buffer that turns a warning into a short MP4 clip
=====================================================================================

The student WebSocket already receives every frame for ML analysis. This keeps the last
few seconds in memory; when a warning fires it also waits a few more seconds, then
encodes "before + after" as an H.264 MP4 (browser-playable) for upload to S3.

Raw frames are held in memory only for the lifetime of the session and are discarded
once the clip is encoded. Nothing here talks to the browser/webcam.
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Deque, List, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

PRE_ROLL_SEC  = 6.0     # seconds of footage kept from before the warning
POST_ROLL_SEC = 4.0     # seconds recorded after the warning
CLIP_WIDTH    = 480     # frames are downscaled to this width to keep clips small
MAX_CLIP_FPS  = 10


@dataclass
class _PendingClip:
    token:      object                       # opaque handle the caller gets back (e.g. the event)
    frames:     List[Tuple[float, np.ndarray]]
    finish_at:  float


@dataclass
class ClipRecorder:
    """One per student session. feed() every frame; arm() when a warning fires."""
    pre_roll:  float = PRE_ROLL_SEC
    post_roll: float = POST_ROLL_SEC
    _buffer:   Deque[Tuple[float, np.ndarray]] = field(default_factory=deque)
    _pending:  List[_PendingClip] = field(default_factory=list)

    @staticmethod
    def _shrink(frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if w <= CLIP_WIDTH:
            return frame.copy()
        return cv2.resize(frame, (CLIP_WIDTH, int(h * CLIP_WIDTH / w)))

    def feed(self, frame_bgr: np.ndarray, now: Optional[float] = None) -> List[Tuple[object, List[Tuple[float, np.ndarray]]]]:
        """Add a frame. Returns (token, frames) for every clip whose post-roll just finished."""
        now = time.time() if now is None else now
        small = self._shrink(frame_bgr)
        self._buffer.append((now, small))
        while self._buffer and now - self._buffer[0][0] > self.pre_roll:
            self._buffer.popleft()

        done = []
        for clip in list(self._pending):
            clip.frames.append((now, small))
            if now >= clip.finish_at:
                self._pending.remove(clip)
                done.append((clip.token, clip.frames))
        return done

    def arm(self, token: object, now: Optional[float] = None) -> None:
        """A warning fired: snapshot the pre-roll and keep collecting for post_roll seconds."""
        now = time.time() if now is None else now
        self._pending.append(_PendingClip(token=token, frames=list(self._buffer), finish_at=now + self.post_roll))

    def flush(self) -> List[Tuple[object, List[Tuple[float, np.ndarray]]]]:
        """Session ended: finish any clips still waiting for post-roll."""
        done = [(c.token, c.frames) for c in self._pending]
        self._pending.clear()
        return done


def _ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return "ffmpeg"   # fall back to one on PATH


def encode_mp4(frames: List[Tuple[float, np.ndarray]]) -> Optional[bytes]:
    """
    Encode timestamped frames to a browser-playable H.264 MP4 (in memory).
    Returns None if there is nothing to encode or ffmpeg fails.
    """
    if len(frames) < 2:
        return None
    duration = max(frames[-1][0] - frames[0][0], 0.5)
    fps = max(1.0, min(MAX_CLIP_FPS, (len(frames) - 1) / duration))

    h, w = frames[0][1].shape[:2]
    w, h = w - w % 2, h - h % 2          # yuv420p needs even dimensions

    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4", "-",
    ]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        raw = b"".join(np.ascontiguousarray(f[:h, :w]).tobytes() for _, f in frames)
        out, err = proc.communicate(raw, timeout=60)
        if proc.returncode != 0 or not out:
            logger.warning("ffmpeg failed: %s", err.decode(errors="ignore")[:300])
            return None
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Clip encoding failed: %s", exc)
        return None


def encode_and_upload(
    frames: List[Tuple[float, np.ndarray]],
    key: str,
    uploader: Callable[[str, bytes], bool],
) -> bool:
    """Blocking helper (run in a thread): encode then upload. True if the clip reached S3."""
    data = encode_mp4(frames)
    if data is None:
        return False
    return uploader(key, data)
