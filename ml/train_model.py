"""
ml/train_model.py
-----------------
Train an LSTM Autoencoder for anomaly detection on water-quality sensor data.

Pipeline:
  1.  Load combined_data.csv
  2.  Engineer 20 features via feature_engineering module
  3.  Separate normal (is_anomaly==0) and anomaly data
  4.  Fit StandardScaler on NORMAL data only
  5.  Scale all features
  6.  Create sliding-window sequences (length 20)
  7.  Label each sequence (anomalous if ANY reading in the window is anomalous)
  8.  Split normal sequences 80/20 train/test
  9.  Build LSTM Autoencoder
  10. Train on normal sequences only (autoencoder learns normality)
  11. Evaluate with reconstruction error threshold (95th percentile)
  12. Save model, scaler, config, and evaluation plots

Usage:
    python ml/train_model.py
"""

import os
import sys
import json

# ── Path setup (so `from feature_engineering import …` works from any cwd) ───
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import pandas as pd
import joblib

# Non-interactive backend (must be set before pyplot import)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

# TensorFlow / Keras
import tensorflow as tf
from tensorflow import keras
from keras import layers

from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
    classification_report,
    roc_curve,
    roc_auc_score,
)

from feature_engineering import (
    engineer_features,
    create_sequences,
    FEATURE_COLUMNS,
    N_FEATURES,
    SEQUENCE_LENGTH,
)

# ── Reproducibility ──────────────────────────────────────────────────────────
np.random.seed(42)
tf.random.set_seed(42)

# ── Paths ─────────────────────────────────────────────────────────────────────
ML_DIR      = os.path.dirname(__file__)
DATA_DIR    = os.path.join(ML_DIR, "data")
PLOT_DIR    = os.path.join(ML_DIR, "plots")
COMBINED_FILE = os.path.join(DATA_DIR, "combined_data.csv")

MODEL_FILE  = os.path.join(ML_DIR, "model.keras")
SCALER_FILE = os.path.join(ML_DIR, "scaler.joblib")
CONFIG_FILE = os.path.join(ML_DIR, "model_config.json")

# ── Hyperparameters ───────────────────────────────────────────────────────────
EPOCHS          = 100
BATCH_SIZE      = 64
VALIDATION_SPLIT = 0.1
THRESHOLD_PERCENTILE = 95      # percentile on TRAINING errors for threshold
TEST_SPLIT      = 0.20          # fraction of normal sequences held out


# ═════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING & FEATURE ENGINEERING
# ═════════════════════════════════════════════════════════════════════════════

def load_and_engineer(path: str) -> pd.DataFrame | None:
    """Load combined CSV and add 20 engineered features."""
    if not os.path.exists(path):
        print(f"  ✗ Data not found: {path}")
        print("    Run Phase 1 and 2 first (generate_mock_data → combine).")
        return None

    df = pd.read_csv(path, parse_dates=["timestamp"])
    print(f"  Loaded {len(df):,} readings ({df['is_anomaly'].sum():,} anomalies)")

    df = engineer_features(df)
    print(f"  Engineered {N_FEATURES} features: {FEATURE_COLUMNS[:4]}… + {N_FEATURES - 4} more")
    return df


# ═════════════════════════════════════════════════════════════════════════════
# 2. MODEL ARCHITECTURE
# ═════════════════════════════════════════════════════════════════════════════

def build_autoencoder(seq_length: int, n_features: int) -> keras.Model:
    """
    LSTM Autoencoder for sequence reconstruction.

    Architecture:
        Encoder: LSTM(64) → LSTM(32) → Dense(16, relu)
        Decoder: RepeatVector → LSTM(32) → LSTM(64) → TimeDistributed(Dense(n_features))
    """
    inputs = layers.Input(shape=(seq_length, n_features), name="encoder_input")

    # ── Encoder ──────────────────────────────────────────────────────────
    x = layers.LSTM(64, return_sequences=True, name="encoder_lstm_1")(inputs)
    x = layers.LSTM(32, return_sequences=False, name="encoder_lstm_2")(x)

    # ── Bottleneck ───────────────────────────────────────────────────────
    bottleneck = layers.Dense(16, activation="relu", name="bottleneck")(x)

    # ── Decoder ──────────────────────────────────────────────────────────
    x = layers.RepeatVector(seq_length, name="repeat_vector")(bottleneck)
    x = layers.LSTM(32, return_sequences=True, name="decoder_lstm_1")(x)
    x = layers.LSTM(64, return_sequences=True, name="decoder_lstm_2")(x)
    outputs = layers.TimeDistributed(
        layers.Dense(n_features), name="output_dense"
    )(x)

    model = keras.Model(inputs, outputs, name="lstm_autoencoder")
    model.compile(optimizer="adam", loss="mse")
    return model


# ═════════════════════════════════════════════════════════════════════════════
# 3. EVALUATION HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def compute_reconstruction_errors(model: keras.Model, sequences: np.ndarray) -> np.ndarray:
    """
    Compute per-sequence reconstruction error (MSE averaged over timesteps and features).

    Returns
    -------
    np.ndarray, shape (n_sequences,)
    """
    reconstructed = model.predict(sequences, verbose=0)
    # MSE per sample: mean over (timesteps × features)
    errors = np.mean((sequences - reconstructed) ** 2, axis=(1, 2))
    return errors


# ═════════════════════════════════════════════════════════════════════════════
# 4. PLOTTING
# ═════════════════════════════════════════════════════════════════════════════

def plot_training_loss(history, path: str):
    """Plot training and validation loss curves."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(history.history["loss"], label="Training Loss", color="#3b82f6", linewidth=2)
    ax.plot(history.history["val_loss"], label="Validation Loss", color="#f59e0b", linewidth=2)
    ax.set_xlabel("Epoch", fontsize=12, fontweight="600")
    ax.set_ylabel("MSE Loss", fontsize=12, fontweight="600")
    ax.set_title("LSTM Autoencoder — Training Loss", fontsize=14, fontweight="bold", pad=15)
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Saved: {path}")


def plot_error_distribution(normal_errors, anomaly_errors, threshold, path: str):
    """Histogram of reconstruction errors for normal vs anomaly sequences."""
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(normal_errors, bins=80, alpha=0.7, label="Normal", color="#22c55e", density=True)
    if len(anomaly_errors) > 0:
        ax.hist(anomaly_errors, bins=80, alpha=0.7, label="Anomaly", color="#ef4444", density=True)
    ax.axvline(threshold, color="#f59e0b", linestyle="--", linewidth=2,
               label=f"Threshold ({threshold:.6f})")
    ax.set_xlabel("Reconstruction Error (MSE)", fontsize=12, fontweight="600")
    ax.set_ylabel("Density", fontsize=12, fontweight="600")
    ax.set_title("Reconstruction Error Distribution", fontsize=14, fontweight="bold", pad=15)
    ax.legend(fontsize=11)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Saved: {path}")


def plot_confusion_matrix_fig(cm, path: str):
    """Save confusion matrix heatmap."""
    fig, ax = plt.subplots(figsize=(7, 6))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Blues",
        xticklabels=["Normal", "Anomaly"],
        yticklabels=["Normal", "Anomaly"],
        ax=ax,
        annot_kws={"size": 16, "fontweight": "bold"},
        linewidths=1, linecolor="white",
    )
    ax.set_xlabel("Predicted Label", fontsize=12, fontweight="600")
    ax.set_ylabel("True Label", fontsize=12, fontweight="600")
    ax.set_title("Confusion Matrix — LSTM Autoencoder", fontsize=14, fontweight="bold", pad=15)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Saved: {path}")


def plot_roc_curve_fig(y_true, errors, roc_auc, path: str):
    """Save ROC curve (higher error → predicted anomaly)."""
    fpr, tpr, _ = roc_curve(y_true, errors)
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot(fpr, tpr, color="#3b82f6", linewidth=2.5,
            label=f"LSTM Autoencoder (AUC = {roc_auc:.3f})")
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, linewidth=1, label="Random Classifier")
    ax.fill_between(fpr, tpr, alpha=0.1, color="#3b82f6")
    ax.set_xlabel("False Positive Rate", fontsize=12, fontweight="600")
    ax.set_ylabel("True Positive Rate", fontsize=12, fontweight="600")
    ax.set_title("ROC Curve — Anomaly Detection", fontsize=14, fontweight="bold", pad=15)
    ax.legend(fontsize=11, loc="lower right")
    ax.grid(alpha=0.3)
    ax.set_xlim([-0.02, 1.02])
    ax.set_ylim([-0.02, 1.02])
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓ Saved: {path}")


# ═════════════════════════════════════════════════════════════════════════════
# 5. MAIN PIPELINE
# ═════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("Phase 4 — Train & Evaluate LSTM Autoencoder")
    print("=" * 60)

    os.makedirs(PLOT_DIR, exist_ok=True)

    # ── 1. Load & engineer features ──────────────────────────────────────
    print("\n[1/8] Loading data and engineering features…")
    df = load_and_engineer(COMBINED_FILE)
    if df is None:
        return

    # ── 2. Separate normal / anomaly ─────────────────────────────────────
    print("\n[2/8] Separating normal and anomaly data…")
    feature_data = df[FEATURE_COLUMNS].values.astype(np.float32)
    labels = df["is_anomaly"].values

    normal_mask = labels == 0
    anomaly_mask = labels == 1
    print(f"  Normal readings:  {normal_mask.sum():,}")
    print(f"  Anomaly readings: {anomaly_mask.sum():,}")

    # ── 3. Fit scaler on NORMAL data only ────────────────────────────────
    print("\n[3/8] Fitting StandardScaler on normal data…")
    scaler = StandardScaler()
    scaler.fit(feature_data[normal_mask])

    # Scale ALL data (normal + anomaly) using the normal-fitted scaler
    scaled_data = scaler.transform(feature_data).astype(np.float32)

    # ── 4. Create sequences from the FULL sorted dataset ─────────────────
    print(f"\n[4/8] Creating sequences (window={SEQUENCE_LENGTH})…")
    sequences = create_sequences(scaled_data, SEQUENCE_LENGTH)
    print(f"  Total sequences: {len(sequences):,}")

    # Label each sequence: anomalous if ANY reading in the window has is_anomaly==1
    seq_labels = np.zeros(len(sequences), dtype=int)
    for i in range(len(sequences)):
        window_labels = labels[i : i + SEQUENCE_LENGTH]
        if np.any(window_labels == 1):
            seq_labels[i] = 1

    n_normal_seq = (seq_labels == 0).sum()
    n_anomaly_seq = (seq_labels == 1).sum()
    print(f"  Normal sequences:  {n_normal_seq:,}")
    print(f"  Anomaly sequences: {n_anomaly_seq:,}")

    # ── 5. Split normal sequences: 80% train, 20% test ──────────────────
    print(f"\n[5/8] Splitting normal sequences (train={1-TEST_SPLIT:.0%} / test={TEST_SPLIT:.0%})…")
    normal_sequences = sequences[seq_labels == 0]
    anomaly_sequences = sequences[seq_labels == 1]

    n_train = int(len(normal_sequences) * (1 - TEST_SPLIT))
    train_sequences = normal_sequences[:n_train]
    test_normal_sequences = normal_sequences[n_train:]
    print(f"  Train (normal only): {len(train_sequences):,}")
    print(f"  Test  (normal):      {len(test_normal_sequences):,}")
    print(f"  Test  (anomaly):     {len(anomaly_sequences):,}")

    # ── 6. Build model ───────────────────────────────────────────────────
    print(f"\n[6/8] Building LSTM Autoencoder…")
    model = build_autoencoder(SEQUENCE_LENGTH, N_FEATURES)
    model.summary()

    # ── 7. Train ─────────────────────────────────────────────────────────
    print(f"\n[7/8] Training (epochs={EPOCHS}, batch_size={BATCH_SIZE})…")
    history = model.fit(
        train_sequences,
        train_sequences,          # autoencoder: input == target
        epochs=EPOCHS,
        batch_size=BATCH_SIZE,
        validation_split=VALIDATION_SPLIT,
        shuffle=True,
        verbose=1,
    )

    # ── 8. Evaluate ──────────────────────────────────────────────────────
    print(f"\n[8/8] Evaluating…")

    # Reconstruction errors on training data (for threshold)
    train_errors = compute_reconstruction_errors(model, train_sequences)
    threshold = float(np.percentile(train_errors, THRESHOLD_PERCENTILE))
    print(f"  Threshold (P{THRESHOLD_PERCENTILE} of training errors): {threshold:.6f}")

    # Reconstruction errors on test sets
    test_normal_errors = compute_reconstruction_errors(model, test_normal_sequences)
    anomaly_errors = compute_reconstruction_errors(model, anomaly_sequences)

    # Combine test errors and labels
    all_test_errors = np.concatenate([test_normal_errors, anomaly_errors])
    all_test_labels = np.concatenate([
        np.zeros(len(test_normal_errors), dtype=int),
        np.ones(len(anomaly_errors), dtype=int),
    ])

    # Classify using threshold
    y_pred = (all_test_errors > threshold).astype(int)
    y_true = all_test_labels

    # ── Metrics ──────────────────────────────────────────────────────────
    precision = precision_score(y_true, y_pred, zero_division=0)
    recall    = recall_score(y_true, y_pred, zero_division=0)
    f1        = f1_score(y_true, y_pred, zero_division=0)

    try:
        roc_auc = roc_auc_score(y_true, all_test_errors)
    except ValueError:
        roc_auc = 0.0

    cm = confusion_matrix(y_true, y_pred)

    print("\n" + "=" * 50)
    print("  LSTM Autoencoder — Anomaly Detection Results")
    print("  " + "─" * 46)
    print(f"  Precision:  {precision:.4f}")
    print(f"  Recall:     {recall:.4f}")
    print(f"  F1 Score:   {f1:.4f}")
    print(f"  ROC AUC:    {roc_auc:.4f}")
    print("=" * 50)

    print(f"\n  Classification Report:")
    report = classification_report(
        y_true, y_pred,
        target_names=["Normal", "Anomaly"],
        zero_division=0,
    )
    print(report)

    print(f"  Confusion Matrix:")
    print(f"    TN={cm[0][0]:5d}  FP={cm[0][1]:5d}")
    print(f"    FN={cm[1][0]:5d}  TP={cm[1][1]:5d}")

    # ── Save model, scaler, config ───────────────────────────────────────
    print(f"\n  Saving artifacts…")
    model.save(MODEL_FILE)
    print(f"  ✓ Model saved:  {MODEL_FILE}")

    joblib.dump(scaler, SCALER_FILE)
    print(f"  ✓ Scaler saved: {SCALER_FILE}")

    config = {
        "threshold":       threshold,
        "feature_columns": FEATURE_COLUMNS,
        "sequence_length": SEQUENCE_LENGTH,
        "n_features":      N_FEATURES,
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  ✓ Config saved: {CONFIG_FILE}")

    # ── Generate evaluation plots ────────────────────────────────────────
    print(f"\n  Generating evaluation plots…")
    plot_training_loss(history, os.path.join(PLOT_DIR, "training_loss.png"))
    plot_error_distribution(
        test_normal_errors, anomaly_errors, threshold,
        os.path.join(PLOT_DIR, "error_distribution.png"),
    )
    plot_confusion_matrix_fig(cm, os.path.join(PLOT_DIR, "confusion_matrix.png"))
    plot_roc_curve_fig(y_true, all_test_errors, roc_auc,
                       os.path.join(PLOT_DIR, "roc_curve.png"))

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"\n  ╔══════════════════════════════════════════════════╗")
    print(f"  ║  LSTM Autoencoder ready for deployment!          ║")
    print(f"  ║                                                  ║")
    print(f"  ║  Files to commit:                                ║")
    print(f"  ║    • ml/model.keras                              ║")
    print(f"  ║    • ml/scaler.joblib                            ║")
    print(f"  ║    • ml/model_config.json                        ║")
    print(f"  ╚══════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
