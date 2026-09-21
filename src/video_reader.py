"""
video_reader.py — Phase 1: Video Ingestion
===========================================

Responsibilities:
    - Recursively discover .mp4 files under a root dataset directory.
    - Extract per-video metadata: FPS, frame count, duration, resolution.
    - Verify that each video can actually be opened and is non-empty.
    - Derive a behaviour label from the video's directory name.
    - Return frames in chronological order for downstream processing.
    - Handle corrupted or unreadable videos gracefully without crashing.

Usage (standalone):
    python src/video_reader.py
    python src/video_reader.py --dataset dataset --output outputs/metadata.csv

The script prints a metadata table and optionally saves it as CSV.
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Generator, List, Optional

import cv2

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
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class VideoMetadata:
    """All metadata collected for a single video file."""

    path: str
    label: str          # behaviour label derived from parent directory name
    fps: float
    frame_count: int
    duration_s: float   # seconds
    width: int
    height: int
    readable: bool
    error: Optional[str] = field(default=None)

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    def __str__(self) -> str:
        status = "OK" if self.readable else f"ERROR: {self.error}"
        return (
            f"[{status}] {Path(self.path).name}"
            f"  label={self.label}"
            f"  {self.fps:.1f} fps"
            f"  {self.frame_count} frames"
            f"  {self.duration_s:.2f}s"
            f"  {self.resolution}"
        )


# ---------------------------------------------------------------------------
# Label extraction
# ---------------------------------------------------------------------------

def derive_label(video_path: Path) -> str:
    """
    Derive a behaviour label from a video's directory path.

    Strategy: use the immediate parent directory name as the label.

    Examples
    --------
    dataset/movements/eye_rubbing/eye_rubbing_001.mp4  -> 'eye_rubbing'
    dataset/normal/looking_down/looking_down_001.mp4   -> 'looking_down'
    dataset/suspicious/repeated_left/...               -> 'repeated_left'
    """
    return video_path.parent.name


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".mp4", ".avi", ".mov", ".mkv", ".webm")


def discover_videos(
    root: str | Path,
    extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> List[Path]:
    """
    Recursively discover all video files under *root*.

    Files are returned sorted by their full path so that processing order
    is deterministic and reproducible across runs and operating systems.

    Parameters
    ----------
    root:
        Top-level directory to search (e.g. ``"dataset"``).
    extensions:
        Tuple of lowercase file extensions to include.

    Returns
    -------
    Sorted list of Path objects pointing to discovered videos.
    """
    root = Path(root)

    if not root.exists():
        raise FileNotFoundError(f"Dataset root not found: {root.resolve()}")
    if not root.is_dir():
        raise NotADirectoryError(f"Expected a directory, got: {root.resolve()}")

    found: List[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            found.append(path)

    found.sort()
    logger.info("Discovered %d video file(s) under '%s'", len(found), root)
    return found


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def read_video_metadata(video_path: str | Path) -> VideoMetadata:
    """
    Open *video_path* with OpenCV and extract metadata.

    If the file cannot be opened or has zero frames, ``readable`` is set to
    ``False`` and ``error`` contains a human-readable description.  The
    function never raises an exception — all errors are caught and reported
    in the returned ``VideoMetadata`` object.

    Parameters
    ----------
    video_path:
        Absolute or relative path to the video file.

    Returns
    -------
    ``VideoMetadata`` instance (always, even on failure).
    """
    path = Path(video_path)
    label = derive_label(path)

    # Failure sentinel
    def _failed(reason: str) -> VideoMetadata:
        logger.warning("Unreadable video '%s': %s", path.name, reason)
        return VideoMetadata(
            path=str(path),
            label=label,
            fps=0.0,
            frame_count=0,
            duration_s=0.0,
            width=0,
            height=0,
            readable=False,
            error=reason,
        )

    if not path.exists():
        return _failed("File not found")

    cap: cv2.VideoCapture = cv2.VideoCapture(str(path))

    if not cap.isOpened():
        cap.release()
        return _failed("cv2.VideoCapture could not open file")

    try:
        fps: float = cap.get(cv2.CAP_PROP_FPS)
        frame_count: int = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width: int = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height: int = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if frame_count <= 0:
            return _failed("Frame count reported as zero or negative")

        if fps <= 0:
            # Some containers do not store FPS reliably; fall back to 30
            logger.warning(
                "'%s': FPS reported as %.1f, defaulting to 30.0", path.name, fps
            )
            fps = 30.0

        duration_s: float = frame_count / fps

        # Quick sanity read: attempt to grab the first frame
        ret, _ = cap.read()
        if not ret:
            return _failed("Could not read first frame (file may be corrupted)")

    except Exception as exc:  # noqa: BLE001
        return _failed(f"Unexpected error during metadata read: {exc}")

    finally:
        cap.release()

    meta = VideoMetadata(
        path=str(path),
        label=label,
        fps=fps,
        frame_count=frame_count,
        duration_s=duration_s,
        width=width,
        height=height,
        readable=True,
    )
    logger.debug("OK  %s", meta)
    return meta


# ---------------------------------------------------------------------------
# Batch metadata scan
# ---------------------------------------------------------------------------

def scan_dataset(
    root: str | Path,
    extensions: tuple[str, ...] = SUPPORTED_EXTENSIONS,
) -> List[VideoMetadata]:
    """
    Discover and read metadata for every video under *root*.

    Parameters
    ----------
    root:
        Top-level dataset directory.
    extensions:
        File extensions to include.

    Returns
    -------
    List of ``VideoMetadata`` objects, one per discovered video.
    """
    video_paths = discover_videos(root, extensions)
    results: List[VideoMetadata] = []

    for vp in video_paths:
        meta = read_video_metadata(vp)
        results.append(meta)

    readable = sum(1 for m in results if m.readable)
    failed = len(results) - readable
    logger.info(
        "Metadata scan complete: %d readable, %d unreadable/failed", readable, failed
    )
    return results


# ---------------------------------------------------------------------------
# Frame reading
# ---------------------------------------------------------------------------

def read_frames(
    video_path: str | Path,
    max_frames: Optional[int] = None,
) -> Generator[tuple[int, object], None, None]:
    """
    Yield ``(frame_index, frame)`` tuples from *video_path* in chronological order.

    Frames are yielded as BGR NumPy arrays (OpenCV default).

    Parameters
    ----------
    video_path:
        Path to the video file.
    max_frames:
        If set, stop after yielding this many frames.

    Yields
    ------
    (frame_index, frame)
        ``frame_index`` is 0-based.  ``frame`` is a ``(H, W, 3)`` uint8 array.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    RuntimeError
        If OpenCV cannot open the file.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open: {path}")

    try:
        frame_idx = 0
        while True:
            if max_frames is not None and frame_idx >= max_frames:
                break
            ret, frame = cap.read()
            if not ret:
                break
            yield frame_idx, frame
            frame_idx += 1
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def save_metadata_csv(metadata: List[VideoMetadata], output_path: str | Path) -> None:
    """
    Write *metadata* to a CSV file at *output_path*.

    Parameters
    ----------
    metadata:
        List of ``VideoMetadata`` objects to save.
    output_path:
        Destination file path.  Parent directories are created if needed.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "path", "label", "fps", "frame_count",
        "duration_s", "width", "height", "readable", "error",
    ]

    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in metadata:
            row = asdict(m)
            # asdict includes every field; keep only our declared columns
            writer.writerow({k: row[k] for k in fieldnames})

    logger.info("Metadata saved to '%s'", output_path)


# ---------------------------------------------------------------------------
# Pretty-print summary table
# ---------------------------------------------------------------------------

def print_summary(metadata: List[VideoMetadata]) -> None:
    """Print a human-readable summary table to stdout."""
    col_w = {
        "label": 22,
        "fps": 7,
        "frames": 8,
        "duration": 10,
        "resolution": 12,
        "status": 28,
    }

    header = (
        f"{'Label':<{col_w['label']}}"
        f"{'FPS':>{col_w['fps']}}"
        f"{'Frames':>{col_w['frames']}}"
        f"{'Duration':>{col_w['duration']}}"
        f"{'Resolution':>{col_w['resolution']}}"
        f"  {'Status'}"
    )
    separator = "-" * len(header)

    print()
    print("=" * len(header))
    print("  VIDEO METADATA REPORT")
    print("=" * len(header))
    print(header)
    print(separator)

    for m in metadata:
        status = "OK" if m.readable else f"FAILED: {m.error}"
        print(
            f"{m.label:<{col_w['label']}}"
            f"{m.fps:>{col_w['fps']}.1f}"
            f"{m.frame_count:>{col_w['frames']}}"
            f"{m.duration_s:>{col_w['duration']}.2f}s"
            f"{m.resolution:>{col_w['resolution']}}"
            f"  {status}"
        )

    print(separator)
    readable = sum(1 for m in metadata if m.readable)
    failed = len(metadata) - readable
    print(f"  Total: {len(metadata)} videos | Readable: {readable} | Failed: {failed}")
    print("=" * len(header))
    print()

    # Warn about empty classes
    labels = [m.label for m in metadata if m.readable]
    from collections import Counter
    counts = Counter(labels)
    low = {lbl: n for lbl, n in counts.items() if n < 5}
    if low:
        print("WARNING: The following classes have fewer than 5 videos.")
        print("The current dataset is a prototype and CANNOT support")
        print("reliable generalisation claims.\n")
        for lbl, n in sorted(low.items()):
            print(f"  {lbl}: {n} video(s)")
        print()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 1 — Video ingestion: scan dataset and report metadata."
    )
    parser.add_argument(
        "--dataset",
        default="dataset",
        help="Root dataset directory (default: dataset)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to save metadata CSV (e.g. outputs/metadata.csv)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("Starting video metadata scan — dataset root: '%s'", args.dataset)

    try:
        metadata = scan_dataset(args.dataset)
    except (FileNotFoundError, NotADirectoryError) as exc:
        logger.error("%s", exc)
        raise SystemExit(1) from exc

    print_summary(metadata)

    if args.output:
        save_metadata_csv(metadata, args.output)
    else:
        logger.info(
            "Tip: use --output outputs/metadata.csv to save the report as CSV."
        )


if __name__ == "__main__":
    main()
