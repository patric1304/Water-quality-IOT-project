"""
monitor/ml_inference.py
-----------------------
LSTM Autoencoder inference for the Django backend.

Provides the ``predict_anomaly()`` function that views.py calls on every
incoming batch of sensor readings.  Because the LSTM Autoencoder needs a
*sequence* of readings (not a single point), the function signature accepts
a list of recent readings.

Usage (from Django views.py):
    from .ml_inference import predict_anomaly

    result = predict_anomaly(recent_readings_list)
    if result:
        reading.is_anomaly    = result["is_anomaly"]
        reading.anomaly_score = result["anomaly_score"]
        reading.ml_confidence = result["confidence"]
        reading.save()
"""

import os
import sys
import json
import logging

import numpy as np
import pandas as pd
import joblib

logger = logging.getLogger(__name__)

# ── Path resolution ──────────────────────────────────────────────────────────
# backend/monitor/ml_inference.py  →  backend/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Try backend/ml/ first (Render Docker), then repo-root/ml/ (local dev)
ML_DIR_LOCAL = os.path.normpath(os.path.join(BASE_DIR, "ml"))
ML_DIR_REPO  = os.path.normpath(os.path.join(BASE_DIR, "..", "ml"))
ML_DIR = ML_DIR_LOCAL if os.path.isdir(ML_DIR_LOCAL) else ML_DIR_REPO

MODEL_PATH  = os.path.join(ML_DIR, "model.keras")
SCALER_PATH = os.path.join(ML_DIR, "scaler.joblib")
CONFIG_PATH = os.path.join(ML_DIR, "model_config.json")

# ── Add ml/ to sys.path so we can import feature_engineering ─────────────────
if ML_DIR not in sys.path:
    sys.path.insert(0, ML_DIR)

from feature_engineering import engineer_features, FEATURE_COLUMNS, SEQUENCE_LENGTH

# ── Lazy-loaded singletons ───────────────────────────────────────────────────
_model = None
_scaler = None
_config = None


def _load():
    """Load the Keras model, scaler, and config from disk (once)."""
    global _model, _scaler, _config

    if _model is not None:
        return  # already loaded

    model_path  = os.path.normpath(MODEL_PATH)
    scaler_path = os.path.normpath(SCALER_PATH)
    config_path = os.path.normpath(CONFIG_PATH)

    logger.info("Loading LSTM Autoencoder model from %s", model_path)

    # Use lightweight tflite_runtime instead of keras
    import tflite_runtime.interpreter as tflite
    _model = tflite.Interpreter(model_path=model_path)
    _model.allocate_tensors()

    logger.info("Loading scaler from %s", scaler_path)
    _scaler = joblib.load(scaler_path)

    logger.info("Loading config from %s", config_path)
    with open(config_path, "r") as f:
        _config = json.load(f)


def predict_anomaly(recent_readings):
    """
    Run LSTM Autoencoder inference on recent sensor readings.

    Parameters
    ----------
    recent_readings : list of dict
        List of recent readings, each with keys:
        ``ph``, ``temperature``, ``tds``, ``turbidity``, ``timestamp``.
        Must have at least ``SEQUENCE_LENGTH + 5`` (= 25) readings for
        proper feature computation (rolling windows, deltas).
        Should be sorted by timestamp (oldest first).

    Returns
    -------
    dict or None
        ``{"is_anomaly": bool, "anomaly_score": float, "confidence": str}``
        where ``anomaly_score`` is the reconstruction error (higher = more
        anomalous) and ``confidence`` is ``'high'``, ``'medium'``, or
        ``'low'``.  Returns ``None`` if model files are not found or
        insufficient readings are provided.
    """
    # ── Minimum readings check ───────────────────────────────────────────
    min_required = SEQUENCE_LENGTH + 5  # need extra for rolling/delta features
    if recent_readings is None or len(recent_readings) < min_required:
        logger.warning(
            "Insufficient readings for LSTM inference: need %d, got %d",
            min_required,
            0 if recent_readings is None else len(recent_readings),
        )
        return None

    # ── Load model artefacts ─────────────────────────────────────────────
    try:
        _load()
    except FileNotFoundError:
        logger.warning("ML model files not found — skipping inference")
        return None
    except Exception as e:
        logger.error("Failed to load ML model: %s", e)
        return None

    try:
        # ── Build DataFrame from recent readings ─────────────────────────
        df = pd.DataFrame(recent_readings)

        # ── Engineer features ────────────────────────────────────────────
        df = engineer_features(df)

        # ── Get feature columns used during training ─────────────────────
        feature_cols = _config.get("feature_columns", FEATURE_COLUMNS)
        seq_length   = _config.get("sequence_length", SEQUENCE_LENGTH)

        # Take the last `seq_length` rows of engineered features
        feature_data = df[feature_cols].values.astype(np.float32)
        if len(feature_data) < seq_length:
            logger.warning(
                "Not enough rows after feature engineering: need %d, got %d",
                seq_length, len(feature_data),
            )
            return None

        last_window = feature_data[-seq_length:]

        # ── Scale with saved scaler ──────────────────────────────────────
        scaled_window = _scaler.transform(last_window).astype(np.float32)

        # ── Reshape to (1, seq_length, n_features) ───────────────────────
        input_seq = scaled_window.reshape(1, seq_length, -1)

        # ── Predict (reconstruct) using TFLite ───────────────────────────
        input_details = _model.get_input_details()
        output_details = _model.get_output_details()
        _model.set_tensor(input_details[0]['index'], input_seq)
        _model.invoke()
        reconstructed = _model.get_tensor(output_details[0]['index'])

        # ── Compute reconstruction error (MSE on LAST timestep only) ────
        error = float(np.mean((input_seq[0, -1, :] - reconstructed[0, -1, :]) ** 2))

        # ── Compare to threshold ─────────────────────────────────────────
        threshold = _config["threshold"]
        is_anomaly = error > threshold

        # ── Determine confidence ─────────────────────────────────────────
        if error > 2 * threshold:
            confidence = "high"
        elif error > 1.5 * threshold:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "is_anomaly":    bool(is_anomaly),
            "anomaly_score": round(float(error), 6),
            "confidence":    confidence,
        }

    except Exception as e:
        logger.error("LSTM inference failed: %s", e)
        return None
