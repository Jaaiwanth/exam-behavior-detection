"""
setup_models.py — Download MediaPipe task model files
======================================================

MediaPipe 1.0+ uses the Tasks API, which requires pre-trained .task model files.
This script downloads the three model files needed for Phase 2:

    models/face_landmarker.task     — FaceMesh (478 landmarks + blendshapes)
    models/hand_landmarker.task     — Hand landmarks (21 points per hand)
    models/pose_landmarker.task     — Body pose landmarks (33 points)

Model files are downloaded from the official MediaPipe model repository.
They are excluded from Git by .gitignore (models/*.task).

Usage:
    py -3.11 setup_models.py
    python setup_models.py
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model download URLs (official MediaPipe model CDN)
# ---------------------------------------------------------------------------

MODELS_DIR = Path("models")

MODEL_URLS: dict[str, str] = {
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
    ),
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
    ),
    "pose_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
    ),
}


def _download_file(url: str, dest: Path) -> None:
    """Download *url* to *dest*, printing progress."""
    logger.info("Downloading: %s", dest.name)
    logger.info("  URL: %s", url)

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100, downloaded * 100 // total_size)
            mb = downloaded / 1_048_576
            total_mb = total_size / 1_048_576
            print(f"\r  {pct:3d}%  {mb:.1f} / {total_mb:.1f} MB", end="", flush=True)

    urllib.request.urlretrieve(url, dest, reporthook=_progress)
    print()  # newline after progress
    logger.info("  Saved: %s (%.1f MB)", dest, dest.stat().st_size / 1_048_576)


def setup_models(models_dir: Path = MODELS_DIR, force: bool = False) -> None:
    """
    Download all required model files to *models_dir*.

    Parameters
    ----------
    models_dir:
        Directory to save model files (default: models/).
    force:
        If True, re-download even if the file already exists.
    """
    models_dir.mkdir(parents=True, exist_ok=True)

    for filename, url in MODEL_URLS.items():
        dest = models_dir / filename
        if dest.exists() and not force:
            logger.info("Already exists (skip): %s", filename)
            continue
        try:
            _download_file(url, dest)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download %s: %s", filename, exc)
            raise

    logger.info("All model files ready in '%s'", models_dir)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download MediaPipe task model files.")
    parser.add_argument(
        "--models-dir", default="models", help="Directory to save models (default: models)"
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-download even if files already exist"
    )
    args = parser.parse_args()

    setup_models(Path(args.models_dir), force=args.force)
