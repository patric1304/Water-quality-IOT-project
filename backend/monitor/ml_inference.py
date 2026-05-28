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

MODEL_PATH  = os.path.join(ML_DIR, "model.onnx")
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
    """Load the ONNX model, scaler, and config from disk (once)."""
    global _model, _scaler, _config

    if _model is not None:
        return  # already loaded

    model_path  = os.path.normpath(MODEL_PATH)
    scaler_path = os.path.normpath(SCALER_PATH)
    config_path = os.path.normpath(CONFIG_PATH)

    logger.info("Loading LSTM Autoencoder model from %s", model_path)

    # Use ONNX Runtime — lightweight (~30 MB), native LSTM support, NumPy 2.x OK
    import onnxruntime as ort
    _model = ort.InferenceSession(model_path)

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

        # ── Predict (reconstruct) using ONNX Runtime ────────────────────
        input_name = _model.get_inputs()[0].name
        reconstructed = _model.run(None, {input_name: input_seq})[0]

        # ── Compute reconstruction error (MSE on LAST timestep only) ────
        diff = input_seq[0, -1, :] - reconstructed[0, -1, :]
        error = float(np.mean(diff ** 2))

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

        # ── Compute feature-specific reconstruction errors ────────────────
        ph_err = float(diff[0] ** 2)
        temp_err = float(diff[1] ** 2)
        tds_err = float(diff[2] ** 2)
        turb_err = float(diff[3] ** 2)

        raw_errors = {
            "ph": ph_err,
            "temperature": temp_err,
            "tds": tds_err,
            "turbidity": turb_err,
        }
        
        logger.debug("Raw reconstruction errors: %s", raw_errors)

        anomalous_features = {k: False for k in raw_errors}
        if is_anomaly:
            # 1. Flag the feature with the maximum reconstruction error (fallback/primary driver)
            max_error = max(raw_errors.values())
            for k, v in raw_errors.items():
                if v == max_error:
                    anomalous_features[k] = True

            # 2. Flag features that violate their basic safe thresholds (domain-specific checks)
            # ph: [6.5, 8.5], temp: [15.0, 30.0], tds: <= 400.0, turbidity: <= 4.0
            last_reading = recent_readings[-1]
            
            ph_val = last_reading.get("ph")
            if ph_val is not None:
                try:
                    ph_val = float(ph_val)
                    if ph_val < 6.5 or ph_val > 8.5:
                        anomalous_features["ph"] = True
                except (ValueError, TypeError):
                    pass

            temp_val = last_reading.get("temperature")
            if temp_val is not None:
                try:
                    temp_val = float(temp_val)
                    if temp_val < 15.0 or temp_val > 30.0:
                        anomalous_features["temperature"] = True
                except (ValueError, TypeError):
                    pass

            tds_val = last_reading.get("tds")
            if tds_val is not None:
                try:
                    tds_val = float(tds_val)
                    if tds_val > 400.0:
                        anomalous_features["tds"] = True
                except (ValueError, TypeError):
                    pass

            turb_val = last_reading.get("turbidity")
            if turb_val is not None:
                try:
                    turb_val = float(turb_val)
                    if turb_val > 4.0:
                        anomalous_features["turbidity"] = True
                except (ValueError, TypeError):
                    pass

            # 3. Flag other features with significant errors contributing to the anomaly
            for k, v in raw_errors.items():
                if v >= 5.0 and v >= 0.35 * max_error:
                    anomalous_features[k] = True

        return {
            "is_anomaly":    bool(is_anomaly),
            "anomaly_score": round(float(error), 6),
            "confidence":    confidence,
            "anomalous_features": anomalous_features,
        }

    except Exception as e:
        logger.error("LSTM inference failed: %s", e)
        return None
