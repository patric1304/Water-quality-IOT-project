"""
ml/feature_engineering.py
-------------------------
Shared feature engineering module for the LSTM Autoencoder pipeline.

Transforms 4 raw sensor values into 20 engineered features:
  - Raw sensors (4):          ph, temperature, tds, turbidity
  - Delta / change (4):       ph_delta, temperature_delta, tds_delta, turbidity_delta
  - Rolling mean (4, w=5):    ph_rolling_mean, temperature_rolling_mean, ...
  - Rolling std  (4, w=5):    ph_rolling_std,  temperature_rolling_std, ...
  - Cross-sensor ratios (2):  ph_tds_ratio, tds_turbidity_ratio
  - Cyclical time (2):        hour_sin, hour_cos

Usage:
    from feature_engineering import (
        engineer_features, create_sequences,
        FEATURE_COLUMNS, SENSORS, N_FEATURES, SEQUENCE_LENGTH,
    )

    df = engineer_features(df)                          # adds 20 feature columns
    sequences = create_sequences(data_2d, seq_length)   # → 3D numpy array
"""

import numpy as np
import pandas as pd

# ── Constants ─────────────────────────────────────────────────────────────────

SENSORS = ["ph", "temperature", "tds", "turbidity"]
"""The 4 raw sensor column names."""

ROLLING_WINDOW = 5
"""Window size for rolling mean/std features."""

SEQUENCE_LENGTH = 20
"""Number of timesteps in each LSTM input sequence."""

# ── Feature column definitions (order matters — must match training) ──────────

# 1. Raw sensors (4)
_raw_features = list(SENSORS)

# 2. Delta features (4)
_delta_features = [f"{s}_delta" for s in SENSORS]

# 3. Rolling mean features (4)
_rolling_mean_features = [f"{s}_rolling_mean" for s in SENSORS]

# 4. Rolling std features (4)
_rolling_std_features = [f"{s}_rolling_std" for s in SENSORS]

# 5. Cross-sensor ratios (2)
_ratio_features = ["ph_tds_ratio", "tds_turbidity_ratio"]

# 6. Cyclical time encoding (2)
_time_features = ["hour_sin", "hour_cos"]

FEATURE_COLUMNS = (
    _raw_features
    + _delta_features
    + _rolling_mean_features
    + _rolling_std_features
    + _ratio_features
    + _time_features
)
"""Ordered list of all 20 engineered feature column names."""

N_FEATURES = len(FEATURE_COLUMNS)
"""Total number of engineered features (20)."""

# Sanity check at import time
assert N_FEATURES == 20, f"Expected 20 features, got {N_FEATURES}"

# ── Default fill values for missing sensor readings ──────────────────────────

_FILL_DEFAULTS = {
    "ph":          7.0,
    "temperature": 23.0,
    "tds":         108.0,
    "turbidity":   2.0,
}


# ── Public API ────────────────────────────────────────────────────────────────

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 20 engineered feature columns to a DataFrame of sensor readings.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: ``ph``, ``temperature``, ``tds``, ``turbidity``,
        ``timestamp``.  Rows are individual sensor readings.

    Returns
    -------
    pd.DataFrame
        The same DataFrame (sorted by timestamp, index reset) with 20 new
        feature columns appended.  Any pre-existing feature columns with
        the same names are overwritten.

    Notes
    -----
    - Missing sensor values are filled with safe defaults (see
      ``_FILL_DEFAULTS``) *before* any feature computation.
    - Rolling statistics use ``min_periods=1`` so early rows are still valid
      (they just have a shorter effective window).
    """
    # Work on a copy to avoid mutating the caller's frame
    df = df.copy()

    # ── 0. Ensure timestamp is datetime & sort ────────────────────────────
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # ── 1. Fill nulls with safe defaults ──────────────────────────────────
    for col, default in _FILL_DEFAULTS.items():
        df[col] = df[col].fillna(default)

    # ── 2. Raw sensor values (already present) ────────────────────────────
    # Nothing to compute — they're the first 4 features.

    # ── 3. Delta / change from previous reading ──────────────────────────
    for sensor in SENSORS:
        df[f"{sensor}_delta"] = df[sensor].diff().fillna(0.0)

    # ── 4. Rolling mean (window=5) ────────────────────────────────────────
    for sensor in SENSORS:
        df[f"{sensor}_rolling_mean"] = (
            df[sensor]
            .rolling(window=ROLLING_WINDOW, min_periods=1)
            .mean()
        )

    # ── 5. Rolling std (window=5) ─────────────────────────────────────────
    for sensor in SENSORS:
        df[f"{sensor}_rolling_std"] = (
            df[sensor]
            .rolling(window=ROLLING_WINDOW, min_periods=1)
            .std()
            .fillna(0.0)
        )

    # ── 6. Cross-sensor ratios ────────────────────────────────────────────
    df["ph_tds_ratio"]       = df["ph"]  / (df["tds"] + 1e-6)
    df["tds_turbidity_ratio"] = df["tds"] / (df["turbidity"] + 1e-6)

    # ── 7. Cyclical time encoding ─────────────────────────────────────────
    hour = df["timestamp"].dt.hour + df["timestamp"].dt.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)

    return df


def create_sequences(
    data: np.ndarray,
    seq_length: int = SEQUENCE_LENGTH,
) -> np.ndarray:
    """
    Create overlapping sliding-window sequences from a 2D feature array.

    Parameters
    ----------
    data : np.ndarray, shape (n_samples, n_features)
        Scaled (or unscaled) feature matrix, sorted by time.
    seq_length : int, optional
        Number of timesteps per sequence.  Defaults to ``SEQUENCE_LENGTH``.

    Returns
    -------
    np.ndarray, shape (n_sequences, seq_length, n_features)
        3D array of overlapping windows.  ``n_sequences = n_samples - seq_length + 1``.

    Raises
    ------
    ValueError
        If ``data`` has fewer rows than ``seq_length``.
    """
    n_samples, n_features = data.shape
    if n_samples < seq_length:
        raise ValueError(
            f"Need at least {seq_length} samples to create sequences, "
            f"got {n_samples}."
        )

    n_sequences = n_samples - seq_length + 1
    sequences = np.empty((n_sequences, seq_length, n_features), dtype=data.dtype)
    for i in range(n_sequences):
        sequences[i] = data[i : i + seq_length]

    return sequences
