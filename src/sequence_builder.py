"""
sequence_builder.py — Phase 4: Temporal Sequence Generation
============================================================

Converts per-video feature matrices (T, N_FEATURES) into fixed-length
sliding-window sequences suitable for LSTM training.

Architecture
------------
Each video produces a (T, 38) float32 feature matrix (from Phase 3).
This module:
  1. Loads all .npy files from outputs/frame_features/.
  2. Applies a sliding window of length `window_size` with `stride` step.
  3. Assigns an integer label to every window (from the video's class).
  4. Optionally standardises features (z-score, per-feature statistics
     computed from the training split only — no leakage).
  5. Splits windows into train / val / test sets (stratified by label).
  6. Saves:
       outputs/sequences/X_train.npy   (N_train, window, 38)
       outputs/sequences/X_val.npy     (N_val,   window, 38)
       outputs/sequences/X_test.npy    (N_test,  window, 38)
       outputs/sequences/y_train.npy   (N_train,)
       outputs/sequences/y_val.npy     (N_val,)
       outputs/sequences/y_test.npy    (N_test,)
       outputs/sequences/label_map.json  {int: label_str}
       outputs/sequences/scaler.npz    mean & std for inference

Default parameters (all tunable via CLI):
  --window-size   30      ≈ 1 second at ~30 fps
  --stride        10      75% overlap between windows
  --val-split     0.15    15% of windows for validation
  --test-split    0.15    15% of windows for test
  --standardise         Apply z-score standardisation (recommended)

Usage
-----
    py -3.11 src/sequence_builder.py
    py -3.11 src/sequence_builder.py --window-size 45 --stride 15
    py -3.11 src/sequence_builder.py --features-dir outputs/frame_features --output-dir outputs/sequences

As a module:
    from src.sequence_builder import build_sequences, load_sequences
    X_train, y_train, X_val, y_val, X_test, y_test, label_map = load_sequences()
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_FEATURES_DIR = Path("outputs/frame_features")
DEFAULT_OUTPUT_DIR   = Path("outputs/sequences")
DEFAULT_WINDOW_SIZE  = 30   # frames  (~1 second at 30 fps)
DEFAULT_STRIDE       = 10   # frames  (75% overlap)
DEFAULT_VAL_SPLIT    = 0.15
DEFAULT_TEST_SPLIT   = 0.15
DEFAULT_SEED         = 42


# ---------------------------------------------------------------------------
# Sliding window
# ---------------------------------------------------------------------------

def sliding_windows(
    feature_matrix: np.ndarray,
    window_size: int,
    stride: int,
) -> np.ndarray:
    """
    Cut a (T, F) feature matrix into overlapping windows.

    Parameters
    ----------
    feature_matrix : (T, F) float32
    window_size    : number of frames per window
    stride         : step between window starts

    Returns
    -------
    windows : (N_windows, window_size, F) float32
        Empty array if T < window_size.
    """
    T, F = feature_matrix.shape
    if T < window_size:
        return np.empty((0, window_size, F), dtype=np.float32)

    starts = range(0, T - window_size + 1, stride)
    windows = np.stack(
        [feature_matrix[s : s + window_size] for s in starts], axis=0
    )
    return windows.astype(np.float32)


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------

def load_feature_files(
    features_dir: Path,
) -> Tuple[List[np.ndarray], List[str]]:
    """
    Load all .npy feature files from *features_dir*.

    Returns
    -------
    matrices : list of (T_i, F) arrays
    labels   : list of label strings (one per file)
    """
    manifest = features_dir / "manifest.csv"
    if manifest.exists():
        # Use manifest for guaranteed label↔file mapping
        matrices, labels = [], []
        with open(manifest, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                path = Path(row["path"])
                label = row["label"]
                if not path.exists():
                    logger.warning("Missing file (skipping): %s", path)
                    continue
                mat = np.load(path).astype(np.float32)
                matrices.append(mat)
                labels.append(label)
        logger.info("Loaded %d feature files from manifest.", len(matrices))
    else:
        # Fallback: glob .npy files and extract label from filename prefix
        npy_files = sorted(features_dir.glob("*.npy"))
        matrices, labels = [], []
        for p in npy_files:
            label = p.stem.split("__")[0]
            mat = np.load(p).astype(np.float32)
            matrices.append(mat)
            labels.append(label)
        logger.info("Loaded %d .npy files (no manifest).", len(matrices))

    return matrices, labels


# ---------------------------------------------------------------------------
# Label encoding
# ---------------------------------------------------------------------------

def build_label_map(labels: List[str]) -> Dict[str, int]:
    """
    Create a deterministic label → integer mapping (alphabetical order).

    Returns
    -------
    label_to_int : {'adjusting_glasses': 0, 'drinking_water': 1, ...}
    """
    unique = sorted(set(labels))
    return {lbl: i for i, lbl in enumerate(unique)}


# ---------------------------------------------------------------------------
# Train / val / test split (video-level, then window-level)
# ---------------------------------------------------------------------------

def video_level_split(
    n_videos: int,
    val_frac: float,
    test_frac: float,
    seed: int,
) -> Tuple[List[int], List[int], List[int]]:
    """
    Randomly assign video indices to train / val / test splits.

    Splitting is done at the video level (not window level) to prevent
    data leakage — windows from the same video never appear in both
    train and val/test.

    Returns
    -------
    train_idx, val_idx, test_idx : lists of video indices
    """
    rng = np.random.default_rng(seed)
    indices = np.arange(n_videos)
    rng.shuffle(indices)

    n_test = max(1, int(n_videos * test_frac))
    n_val  = max(1, int(n_videos * val_frac))

    test_idx  = indices[:n_test].tolist()
    val_idx   = indices[n_test : n_test + n_val].tolist()
    train_idx = indices[n_test + n_val :].tolist()

    return train_idx, val_idx, test_idx


# ---------------------------------------------------------------------------
# Standardisation
# ---------------------------------------------------------------------------

def fit_scaler(X_train: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Compute per-feature mean and std from training windows.

    Parameters
    ----------
    X_train : (N, T, F)

    Returns
    -------
    mean : (F,)
    std  : (F,)  — clipped at 1e-6 to avoid div-by-zero
    """
    # Reshape to (N*T, F) for per-feature statistics
    N, T, F = X_train.shape
    flat = X_train.reshape(-1, F)
    mean = flat.mean(axis=0)
    std  = flat.std(axis=0).clip(1e-6)
    return mean.astype(np.float32), std.astype(np.float32)


def apply_scaler(
    X: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
) -> np.ndarray:
    """Standardise a (N, T, F) array using precomputed mean and std."""
    return ((X - mean[None, None, :]) / std[None, None, :]).astype(np.float32)


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_sequences(
    features_dir: Path = DEFAULT_FEATURES_DIR,
    output_dir:   Path = DEFAULT_OUTPUT_DIR,
    window_size:  int  = DEFAULT_WINDOW_SIZE,
    stride:       int  = DEFAULT_STRIDE,
    val_split:    float = DEFAULT_VAL_SPLIT,
    test_split:   float = DEFAULT_TEST_SPLIT,
    standardise:  bool  = True,
    seed:         int   = DEFAULT_SEED,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, Dict[int, str]]:
    """
    Full Phase 4 pipeline: feature files → train/val/test sequence arrays.

    Parameters
    ----------
    features_dir : directory containing .npy files from Phase 3
    output_dir   : where to save X_*.npy, y_*.npy, label_map.json, scaler.npz
    window_size  : frames per sequence (default 30 ≈ 1 s at 30 fps)
    stride       : step between window starts (default 10, 75% overlap)
    val_split    : fraction of videos held out for validation
    test_split   : fraction of videos held out for test
    standardise  : apply z-score standardisation (computed on train only)
    seed         : random seed for reproducibility

    Returns
    -------
    X_train, y_train, X_val, y_val, X_test, y_test, label_map
        X shapes: (N, window_size, N_FEATURES)
        y shapes: (N,) int32
        label_map: {int → label_string}
    """
    features_dir = Path(features_dir)
    output_dir   = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load all feature matrices
    matrices, str_labels = load_feature_files(features_dir)
    if not matrices:
        raise RuntimeError(f"No feature files found in {features_dir}. "
                           "Run Phase 3 first: "
                           "py -3.11 src/feature_extractor.py --dataset dataset")

    label_to_int = build_label_map(str_labels)
    int_to_label = {v: k for k, v in label_to_int.items()}
    n_classes = len(label_to_int)
    n_videos  = len(matrices)

    logger.info("Videos: %d | Classes: %d | Window: %d frames | Stride: %d",
                n_videos, n_classes, window_size, stride)
    logger.info("Classes: %s", list(label_to_int.keys()))

    # 2. Video-level split
    train_idx, val_idx, test_idx = video_level_split(
        n_videos, val_split, test_split, seed
    )
    logger.info("Split  → train: %d videos | val: %d | test: %d",
                len(train_idx), len(val_idx), len(test_idx))

    # 3. Slide windows over each split
    def _collect(indices: List[int]) -> Tuple[np.ndarray, np.ndarray]:
        X_parts, y_parts = [], []
        for i in indices:
            mat   = matrices[i]
            label = label_to_int[str_labels[i]]
            wins  = sliding_windows(mat, window_size, stride)
            if wins.shape[0] == 0:
                logger.warning(
                    "Video %d (%s) too short for window_size=%d (T=%d). Skipping.",
                    i, str_labels[i], window_size, mat.shape[0],
                )
                continue
            X_parts.append(wins)
            y_parts.append(np.full(wins.shape[0], label, dtype=np.int32))

        if not X_parts:
            F = matrices[0].shape[1] if matrices else 38
            return (np.empty((0, window_size, F), dtype=np.float32),
                    np.empty(0, dtype=np.int32))

        return (np.concatenate(X_parts, axis=0),
                np.concatenate(y_parts, axis=0))

    X_train, y_train = _collect(train_idx)
    X_val,   y_val   = _collect(val_idx)
    X_test,  y_test  = _collect(test_idx)

    logger.info("Windows → train: %d | val: %d | test: %d",
                len(X_train), len(X_val), len(X_test))

    # 4. Standardise (fit on train, apply to all)
    if standardise and len(X_train) > 0:
        mean, std = fit_scaler(X_train)
        X_train = apply_scaler(X_train, mean, std)
        if len(X_val)  > 0: X_val  = apply_scaler(X_val,  mean, std)
        if len(X_test) > 0: X_test = apply_scaler(X_test, mean, std)
        np.savez(output_dir / "scaler.npz", mean=mean, std=std)
        logger.info("Scaler saved → scaler.npz  (mean/std of %d features)", len(mean))
    else:
        mean = std = None

    # 5. Save arrays
    np.save(output_dir / "X_train.npy", X_train)
    np.save(output_dir / "y_train.npy", y_train)
    np.save(output_dir / "X_val.npy",   X_val)
    np.save(output_dir / "y_val.npy",   y_val)
    np.save(output_dir / "X_test.npy",  X_test)
    np.save(output_dir / "y_test.npy",  y_test)

    # 6. Save label map (int key as str for JSON compatibility)
    label_map_path = output_dir / "label_map.json"
    with open(label_map_path, "w") as f:
        json.dump({str(k): v for k, v in int_to_label.items()}, f, indent=2)

    # 7. Summary
    _print_summary(
        X_train, y_train, X_val, y_val, X_test, y_test,
        int_to_label, window_size, stride, standardise, output_dir,
        train_idx, val_idx, test_idx, str_labels,
    )

    return X_train, y_train, X_val, y_val, X_test, y_test, int_to_label


def _print_summary(
    X_train, y_train, X_val, y_val, X_test, y_test,
    int_to_label, window_size, stride, standardise, output_dir,
    train_idx, val_idx, test_idx, str_labels,
) -> None:
    """Print a formatted summary of the generated sequence dataset."""
    total = len(X_train) + len(X_val) + len(X_test)
    print(f"\n{'='*62}")
    print(f"  Phase 4 — Temporal Sequence Dataset")
    print(f"{'='*62}")
    print(f"  Window size : {window_size} frames")
    print(f"  Stride      : {stride} frames  ({100*(1-stride/window_size):.0f}% overlap)")
    print(f"  Standardised: {'yes' if standardise else 'no'}")
    print(f"  Output dir  : {output_dir}")
    print(f"{'─'*62}")
    print(f"  {'Split':<10} {'Videos':>7} {'Windows':>9} {'Shape':>20}")
    print(f"  {'─'*56}")
    print(f"  {'train':<10} {len(train_idx):>7} {len(X_train):>9}   {str(X_train.shape)}")
    print(f"  {'val':<10} {len(val_idx):>7}   {len(X_val):>7}   {str(X_val.shape)}")
    print(f"  {'test':<10} {len(test_idx):>7}   {len(X_test):>7}   {str(X_test.shape)}")
    print(f"  {'TOTAL':<10} {'':>7} {total:>9}")
    print(f"{'─'*62}")
    print(f"\n  Class distribution (train windows):")
    if len(y_train) > 0:
        for cls_id, lbl in sorted(int_to_label.items()):
            count = int((y_train == cls_id).sum())
            bar = "█" * (count // max(1, len(y_train) // 30))
            print(f"    [{cls_id:2d}] {lbl:<28} {count:>5}  {bar}")
    print()

    # Videos per split
    print(f"  Video assignment:")
    all_split = [
        ("train", train_idx),
        ("val",   val_idx),
        ("test",  test_idx),
    ]
    for split_name, idxs in all_split:
        vids = [str_labels[i] for i in idxs]
        print(f"    {split_name}: {', '.join(vids)}")
    print()


# ---------------------------------------------------------------------------
# Load helper for downstream phases
# ---------------------------------------------------------------------------

def load_sequences(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
           np.ndarray, np.ndarray, Dict[int, str]]:
    """
    Load pre-built sequence arrays from *output_dir*.

    Returns
    -------
    X_train, y_train, X_val, y_val, X_test, y_test, label_map
    """
    output_dir = Path(output_dir)

    def _load(name: str) -> np.ndarray:
        p = output_dir / name
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found. Run Phase 4 first:\n"
                "  py -3.11 src/sequence_builder.py"
            )
        return np.load(p)

    X_train = _load("X_train.npy")
    y_train = _load("y_train.npy")
    X_val   = _load("X_val.npy")
    y_val   = _load("y_val.npy")
    X_test  = _load("X_test.npy")
    y_test  = _load("y_test.npy")

    label_map_path = output_dir / "label_map.json"
    with open(label_map_path) as f:
        raw = json.load(f)
    label_map = {int(k): v for k, v in raw.items()}

    return X_train, y_train, X_val, y_val, X_test, y_test, label_map


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Phase 4 — Temporal sequence generation.\n"
            "Reads .npy feature files from Phase 3 and produces\n"
            "train/val/test sliding-window arrays for LSTM training."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--features-dir", default=str(DEFAULT_FEATURES_DIR),
                   help=f"Feature files directory (default: {DEFAULT_FEATURES_DIR})")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                   help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    p.add_argument("--window-size", type=int, default=DEFAULT_WINDOW_SIZE,
                   help=f"Frames per window (default: {DEFAULT_WINDOW_SIZE})")
    p.add_argument("--stride", type=int, default=DEFAULT_STRIDE,
                   help=f"Step between windows (default: {DEFAULT_STRIDE})")
    p.add_argument("--val-split", type=float, default=DEFAULT_VAL_SPLIT,
                   help=f"Fraction of videos for val (default: {DEFAULT_VAL_SPLIT})")
    p.add_argument("--test-split", type=float, default=DEFAULT_TEST_SPLIT,
                   help=f"Fraction of videos for test (default: {DEFAULT_TEST_SPLIT})")
    p.add_argument("--no-standardise", action="store_true",
                   help="Skip z-score standardisation.")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED,
                   help=f"Random seed (default: {DEFAULT_SEED})")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    build_sequences(
        features_dir=Path(args.features_dir),
        output_dir=Path(args.output_dir),
        window_size=args.window_size,
        stride=args.stride,
        val_split=args.val_split,
        test_split=args.test_split,
        standardise=not args.no_standardise,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
