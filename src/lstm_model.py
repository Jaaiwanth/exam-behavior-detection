"""
lstm_model.py — Phase 5: LSTM Baseline Classifier
===================================================

Trains a Bidirectional LSTM on the sliding-window sequences from Phase 4
to classify 11 observable exam behaviours.

Architecture
------------
Input  : (batch, 30 frames, 38 features)
         ↓
BiLSTM : 128 units (forward + backward = 256 output), return_sequences=True
         ↓  Dropout 0.4
BiLSTM : 64 units  (forward + backward = 128 output), return_sequences=False
         ↓  Dropout 0.4
Dense  : 64, ReLU + L2 regularisation
         ↓  Dropout 0.3
Dense  : 11, Softmax  → behaviour class probabilities

Why Bidirectional?
  A bidirectional LSTM reads the gesture both forward and backward, which
  helps it capture the build-up AND the recovery of a motion (e.g. the
  head turning away AND returning is a stronger signal than just the turn).

Why small?  With only 114 training windows, a huge network overfits instantly.
  This compact architecture + aggressive dropout is the right tradeoff.

Outputs saved to outputs/models/
  lstm_best.keras      — best val_accuracy checkpoint
  training_history.json— epoch-by-epoch loss/accuracy
  training_curves.png  — loss & accuracy plots
  classification_report.txt — per-class precision/recall/F1 on test set

Usage
-----
    py -3.11 src/lstm_model.py
    py -3.11 src/lstm_model.py --epochs 200 --batch-size 16
    py -3.11 src/lstm_model.py --sequences-dir outputs/sequences --model-dir outputs/models

As a module:
    from src.lstm_model import build_model, load_trained_model
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Tuple

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")   # suppress TF INFO spam

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

DEFAULT_SEQUENCES_DIR = Path("outputs/sequences")
DEFAULT_MODEL_DIR     = Path("outputs/models")
DEFAULT_EPOCHS        = 300
DEFAULT_BATCH_SIZE    = 16
DEFAULT_LEARNING_RATE = 5e-4
DEFAULT_SEED          = 42
DEFAULT_AUG_FACTOR    = 15    # augmented copies per original window


# ---------------------------------------------------------------------------
# Data augmentation for time-series sequences
# ---------------------------------------------------------------------------

def augment_jitter(X: np.ndarray, sigma: float = 0.05) -> np.ndarray:
    """Add Gaussian noise to feature values."""
    return X + np.random.normal(0, sigma, X.shape).astype(np.float32)


def augment_scaling(X: np.ndarray, sigma: float = 0.15) -> np.ndarray:
    """Multiply each feature by a random factor ~N(1, sigma)."""
    # One scale factor per feature, constant across time
    N, T, F = X.shape
    scales = np.random.normal(1.0, sigma, (N, 1, F)).astype(np.float32)
    return X * scales


def augment_time_warp(X: np.ndarray, sigma: float = 0.2) -> np.ndarray:
    """Smooth time-axis warping via interpolation."""
    N, T, F = X.shape
    out = np.empty_like(X)
    for i in range(N):
        # Generate a smooth warp path
        orig = np.linspace(0, T - 1, num=4)
        warped = orig + np.random.normal(0, sigma * T / 4, 4)
        warped = np.clip(warped, 0, T - 1)
        warped[0], warped[-1] = 0, T - 1  # anchor endpoints
        # Build full warp map
        warp_map = np.interp(np.arange(T), orig, warped)
        warp_map = np.clip(warp_map, 0, T - 1)
        for f in range(F):
            out[i, :, f] = np.interp(np.arange(T), warp_map, X[i, :, f])
    return out.astype(np.float32)


def augment_feature_dropout(X: np.ndarray, drop_rate: float = 0.1) -> np.ndarray:
    """Randomly zero out entire features (columns) per window."""
    mask = (np.random.random((X.shape[0], 1, X.shape[2])) > drop_rate).astype(np.float32)
    return X * mask


def augment_magnitude_warp(X: np.ndarray, sigma: float = 0.15) -> np.ndarray:
    """Apply smooth, time-varying scaling to features."""
    N, T, F = X.shape
    out = np.empty_like(X)
    for i in range(N):
        # Generate smooth scaling curve with 4 knot points
        knots = np.random.normal(1.0, sigma, (4, F))
        knot_times = np.linspace(0, T - 1, 4)
        for f in range(F):
            smooth_scale = np.interp(np.arange(T), knot_times, knots[:, f])
            out[i, :, f] = X[i, :, f] * smooth_scale
    return out.astype(np.float32)


def augment_training_data(
    X: np.ndarray,
    y: np.ndarray,
    factor: int = DEFAULT_AUG_FACTOR,
    seed: int = DEFAULT_SEED,
) -> tuple:
    """
    Generate augmented copies of training data.

    Each copy applies a random combination of augmentations.
    Returns (X_augmented, y_augmented) including originals.
    """
    np.random.seed(seed)
    aug_X_parts = [X]  # include originals
    aug_y_parts = [y]

    augmenters = [
        lambda x: augment_jitter(x, sigma=0.05),
        lambda x: augment_scaling(x, sigma=0.15),
        lambda x: augment_time_warp(x, sigma=0.2),
        lambda x: augment_feature_dropout(x, drop_rate=0.1),
        lambda x: augment_magnitude_warp(x, sigma=0.15),
    ]

    for i in range(factor):
        # Apply 2-3 random augmentations per copy
        n_augs = np.random.randint(2, 4)
        chosen = np.random.choice(len(augmenters), n_augs, replace=False)
        X_aug = X.copy()
        for idx in chosen:
            X_aug = augmenters[idx](X_aug)
        aug_X_parts.append(X_aug)
        aug_y_parts.append(y.copy())

    X_out = np.concatenate(aug_X_parts, axis=0)
    y_out = np.concatenate(aug_y_parts, axis=0)

    # Shuffle
    perm = np.random.permutation(len(X_out))
    return X_out[perm], y_out[perm]


# ---------------------------------------------------------------------------
# Model definition
# ---------------------------------------------------------------------------

def build_model(
    n_timesteps: int,
    n_features: int,
    n_classes: int,
    learning_rate: float = DEFAULT_LEARNING_RATE,
) -> "tf.keras.Model":  # noqa: F821
    """
    Build and compile the Bidirectional LSTM classifier.

    Parameters
    ----------
    n_timesteps   : sequence length (window_size from Phase 4, e.g. 30)
    n_features    : feature vector size (38)
    n_classes     : number of behaviour classes (11)
    learning_rate : Adam learning rate

    Returns
    -------
    Compiled Keras model ready for training.
    """
    import tensorflow as tf
    from tensorflow.keras import layers, regularizers

    tf.random.set_seed(DEFAULT_SEED)

    inp = tf.keras.Input(shape=(n_timesteps, n_features), name="sequence_input")

    # --- First BiLSTM (smaller to reduce overfitting on small datasets) ---
    x = layers.Bidirectional(
        layers.LSTM(
            64, return_sequences=False,
            dropout=0.3, recurrent_dropout=0.2,
            kernel_regularizer=regularizers.l2(1e-3),
        ),
        name="bilstm_1",
    )(inp)
    x = layers.Dropout(0.5, name="drop_1")(x)

    # --- Dense head ---
    x = layers.Dense(
        32,
        activation="relu",
        kernel_regularizer=regularizers.l2(1e-3),
        name="dense_1",
    )(x)
    x = layers.Dropout(0.4, name="drop_3")(x)

    out = layers.Dense(n_classes, activation="softmax", name="output")(x)

    model = tf.keras.Model(inputs=inp, outputs=out, name="BehaviourLSTM")

    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )

    return model


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(
    sequences_dir: Path = DEFAULT_SEQUENCES_DIR,
    model_dir:     Path = DEFAULT_MODEL_DIR,
    epochs:        int  = DEFAULT_EPOCHS,
    batch_size:    int  = DEFAULT_BATCH_SIZE,
    learning_rate: float = DEFAULT_LEARNING_RATE,
) -> Tuple["tf.keras.Model", dict]:  # noqa: F821
    """
    Full Phase 5 training pipeline.

    Steps:
      1. Load Phase 4 sequences.
      2. Build BiLSTM model.
      3. Train with:
           - ModelCheckpoint  (save best val_accuracy)
           - EarlyStopping    (patience=30, restore best)
           - ReduceLROnPlateau(patience=10, factor=0.5)
      4. Evaluate on test set.
      5. Save model, history, curves, classification report.

    Returns
    -------
    model   : trained Keras model (best checkpoint weights loaded)
    history : dict of epoch-level metrics
    """
    import tensorflow as tf
    from tensorflow.keras import callbacks

    tf.random.set_seed(DEFAULT_SEED)
    np.random.seed(DEFAULT_SEED)

    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. Load data ---
    logger.info("Loading sequences from %s", sequences_dir)
    sequences_dir = Path(sequences_dir)

    def _load(name: str) -> np.ndarray:
        p = sequences_dir / name
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

    with open(sequences_dir / "label_map.json") as f:
        raw = json.load(f)
    label_map: Dict[int, str] = {int(k): v for k, v in raw.items()}
    class_names = [label_map[i] for i in sorted(label_map)]

    _, n_timesteps, n_features = X_train.shape
    n_classes = len(class_names)

    logger.info(
        "Data shapes (raw) -- train: %s  val: %s  test: %s",
        X_train.shape, X_val.shape, X_test.shape,
    )
    logger.info("Classes (%d): %s", n_classes, class_names)

    # --- 1b. Augment training data ---
    logger.info("Augmenting training data (factor=%d)...", DEFAULT_AUG_FACTOR)
    X_train, y_train = augment_training_data(X_train, y_train, factor=DEFAULT_AUG_FACTOR)
    logger.info("After augmentation — train: %s", X_train.shape)

    # --- 2. Build model ---
    model = build_model(n_timesteps, n_features, n_classes, learning_rate)
    model.summary(print_fn=logger.info)

    # --- 3. Callbacks ---
    best_ckpt = str(model_dir / "lstm_best.keras")

    cb_list = [
        callbacks.ModelCheckpoint(
            filepath=best_ckpt,
            monitor="val_accuracy",
            save_best_only=True,
            mode="max",
            verbose=1,
        ),
        callbacks.EarlyStopping(
            monitor="val_accuracy",
            patience=30,
            restore_best_weights=True,
            verbose=1,
        ),
        callbacks.ReduceLROnPlateau(
            monitor="val_loss",
            factor=0.5,
            patience=10,
            min_lr=1e-6,
            verbose=1,
        ),
    ]

    # --- 4. Compute class weights (handle imbalanced classes) ---
    from sklearn.utils.class_weight import compute_class_weight
    unique_classes = np.unique(y_train)
    weights = compute_class_weight(
        "balanced", classes=unique_classes, y=y_train,
    )
    class_weight = {int(c): float(w) for c, w in zip(unique_classes, weights)}
    logger.info("Class weights: %s", class_weight)

    # --- 5. Train ---
    logger.info(
        "Training: epochs=%d  batch_size=%d  lr=%.4f", epochs, batch_size, learning_rate
    )
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=cb_list,
        class_weight=class_weight,
        verbose=1,
    )

    # --- 5. Evaluate on test set ---
    logger.info("Evaluating on test set...")
    test_loss, test_acc = model.evaluate(X_test, y_test, verbose=0)
    logger.info("Test loss: %.4f | Test accuracy: %.4f", test_loss, test_acc)

    # --- 6. Save history ---
    hist_dict = {k: [float(v) for v in vals] for k, vals in history.history.items()}
    hist_dict["test_loss"]     = test_loss
    hist_dict["test_accuracy"] = test_acc
    hist_path = model_dir / "training_history.json"
    with open(hist_path, "w") as f:
        json.dump(hist_dict, f, indent=2)
    logger.info("History saved → %s", hist_path)

    # --- 7. Training curves ---
    _save_training_curves(hist_dict, model_dir)

    # --- 8. Classification report ---
    _save_classification_report(
        model, X_test, y_test, class_names, model_dir, test_acc
    )

    # --- 9. Print summary ---
    _print_summary(hist_dict, class_names, model_dir)

    return model, hist_dict


# ---------------------------------------------------------------------------
# Helpers: plots, classification report, summary
# ---------------------------------------------------------------------------

def _save_training_curves(hist: dict, model_dir: Path) -> None:
    """Save a loss + accuracy plot to model_dir/training_curves.png."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4))
        fig.suptitle("Phase 5 — LSTM Training Curves", fontsize=13)

        # Loss
        ax1.plot(hist["loss"],     label="Train loss", color="#4C72B0")
        ax1.plot(hist["val_loss"], label="Val loss",   color="#DD8452", linestyle="--")
        ax1.set_title("Loss")
        ax1.set_xlabel("Epoch")
        ax1.set_ylabel("Sparse CE Loss")
        ax1.legend()
        ax1.grid(alpha=0.3)

        # Accuracy
        ax2.plot(hist["accuracy"],     label="Train acc", color="#4C72B0")
        ax2.plot(hist["val_accuracy"], label="Val acc",   color="#DD8452", linestyle="--")
        # Mark test accuracy
        ax2.axhline(
            hist["test_accuracy"], color="#55A868", linestyle=":",
            label=f"Test acc {hist['test_accuracy']:.2%}",
        )
        ax2.set_title("Accuracy")
        ax2.set_xlabel("Epoch")
        ax2.set_ylabel("Accuracy")
        ax2.set_ylim(0, 1.05)
        ax2.legend()
        ax2.grid(alpha=0.3)

        plt.tight_layout()
        out = model_dir / "training_curves.png"
        plt.savefig(out, dpi=120)
        plt.close()
        logger.info("Training curves saved → %s", out)

    except ImportError:
        logger.warning("matplotlib not installed — skipping training curves plot.")


def _save_classification_report(
    model,
    X_test: np.ndarray,
    y_test: np.ndarray,
    class_names: list,
    model_dir: Path,
    test_acc: float,
) -> None:
    """Generate per-class precision / recall / F1 report."""
    try:
        from sklearn.metrics import classification_report, confusion_matrix

        y_pred_probs = model.predict(X_test, verbose=0)
        y_pred       = np.argmax(y_pred_probs, axis=1)

        report = classification_report(
            y_test, y_pred,
            labels=list(range(len(class_names))),
            target_names=class_names,
            zero_division=0,
        )

        cm = confusion_matrix(y_test, y_pred)
        cm_str = "\nConfusion Matrix (rows=true, cols=predicted):\n"
        cm_str += "              " + "  ".join(f"{n[:6]:>6}" for n in class_names) + "\n"
        for i, row in enumerate(cm):
            cm_str += f"{class_names[i][:14]:>14}  " + "  ".join(f"{v:>6}" for v in row) + "\n"

        full_report = (
            f"Phase 5 — LSTM Baseline Classification Report\n"
            f"{'='*54}\n"
            f"Test accuracy: {test_acc:.4f}  ({test_acc:.2%})\n\n"
            f"{report}\n"
            f"{cm_str}"
        )

        out = model_dir / "classification_report.txt"
        out.write_text(full_report)
        logger.info("Classification report saved → %s", out)
        print("\n" + full_report)

    except ImportError:
        logger.warning("scikit-learn not installed — skipping classification report.")


def _print_summary(hist: dict, class_names: list, model_dir: Path) -> None:
    """Print a compact training summary to the console."""
    best_val = max(hist["val_accuracy"])
    best_ep  = int(hist["val_accuracy"].index(best_val)) + 1
    total_ep = len(hist["loss"])
    print(f"\n{'='*54}")
    print(f"  Phase 5 — LSTM Baseline: Training Complete")
    print(f"{'='*54}")
    print(f"  Epochs run       : {total_ep}")
    print(f"  Best val accuracy: {best_val:.4f}  (epoch {best_ep})")
    print(f"  Test accuracy    : {hist['test_accuracy']:.4f}  ({hist['test_accuracy']:.2%})")
    print(f"  Classes          : {len(class_names)}")
    print(f"  Model saved      : {model_dir / 'lstm_best.keras'}")
    print(f"  Curves saved     : {model_dir / 'training_curves.png'}")
    print(f"  Report saved     : {model_dir / 'classification_report.txt'}")
    print(f"{'='*54}\n")


# ---------------------------------------------------------------------------
# Load helper for downstream phases
# ---------------------------------------------------------------------------

def load_trained_model(
    model_dir: Path = DEFAULT_MODEL_DIR,
) -> "tf.keras.Model":  # noqa: F821
    """
    Load the best LSTM checkpoint saved by Phase 5.

    Returns
    -------
    Loaded Keras model.
    """
    import tensorflow as tf

    ckpt = Path(model_dir) / "lstm_best.keras"
    if not ckpt.exists():
        raise FileNotFoundError(
            f"No trained model found at {ckpt}. Run Phase 5 first:\n"
            "  py -3.11 src/lstm_model.py"
        )
    logger.info("Loading model from %s", ckpt)
    return tf.keras.models.load_model(str(ckpt))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Phase 5 — LSTM Baseline Classifier.\n"
            "Trains a Bidirectional LSTM on Phase 4 sliding-window sequences."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sequences-dir", default=str(DEFAULT_SEQUENCES_DIR),
                   help=f"Sequences directory from Phase 4 (default: {DEFAULT_SEQUENCES_DIR})")
    p.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR),
                   help=f"Where to save model + artifacts (default: {DEFAULT_MODEL_DIR})")
    p.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS,
                   help=f"Max training epochs (default: {DEFAULT_EPOCHS})")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                   help=f"Mini-batch size (default: {DEFAULT_BATCH_SIZE})")
    p.add_argument("--lr", type=float, default=DEFAULT_LEARNING_RATE,
                   help=f"Adam learning rate (default: {DEFAULT_LEARNING_RATE})")
    p.add_argument("--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    train(
        sequences_dir=Path(args.sequences_dir),
        model_dir=Path(args.model_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
    )


if __name__ == "__main__":
    main()
