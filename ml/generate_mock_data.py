"""
ml/generate_mock_data.py
------------------------
Phase 1 — Generate synthetic training data for the LSTM Autoencoder model.

Generates ~20,000 sensor readings:
  - ~19,000 normal readings drawn from observed statistical distributions
  - ~1,000 anomalous readings (~5%) with realistic failure modes

Distributions are anchored to the real observed values from the
Raspberry Pi deployment (see ML_INTEGRATION_PLAN.md §"Your Real Observed Values").

Usage:
    python ml/generate_mock_data.py
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ── Configuration ─────────────────────────────────────────────────────────────

SEED = 42
N_NORMAL = 19000
N_ANOMALIES = 1000  # ~5% of total
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "data")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "mock_data.csv")

# Normal distribution parameters (from real observed values)
PARAMS = {
    "ph":          {"mean": 7.2,  "std": 0.4, "clip": (5.5, 9.0)},
    "temperature": {"mean": 23.0, "std": 1.5, "clip": (15.0, 35.0)},
    "tds":         {"mean": 108.0, "std": 15.0, "clip": (50.0, 400.0)},
    "turbidity":   {"mean": 2.0,  "std": 1.2, "clip": (0.0, 20.0)},
}

np.random.seed(SEED)


def generate_timestamps(n, start=None):
    """Generate realistic timestamps at ~15-minute intervals with jitter."""
    if start is None:
        start = datetime(2025, 1, 1, 0, 0, 0)
    timestamps = []
    current = start
    for _ in range(n):
        jitter = timedelta(seconds=np.random.randint(-120, 120))
        timestamps.append(current + jitter)
        current += timedelta(minutes=15)
    return timestamps


def apply_time_variation(df):
    """
    Add realistic time-based variation:
    - Temperature slightly higher during daytime (10am-4pm)
    - Turbidity slightly higher in "usage" windows (7-9am, 6-8pm)
    """
    hours = df["timestamp"].dt.hour

    # Daytime temperature bump (+1.5°C peak at 1pm, Gaussian shape)
    temp_bump = 1.5 * np.exp(-0.5 * ((hours - 13) / 3) ** 2)
    df["temperature"] = df["temperature"] + temp_bump

    # Usage-window turbidity bump
    morning_bump = 0.8 * np.exp(-0.5 * ((hours - 8) / 1.5) ** 2)
    evening_bump = 0.6 * np.exp(-0.5 * ((hours - 19) / 1.5) ** 2)
    df["turbidity"] = df["turbidity"] + morning_bump + evening_bump

    # Small random noise on all channels
    for col in ["ph", "temperature", "tds", "turbidity"]:
        noise = np.random.normal(0, PARAMS[col]["std"] * 0.05, len(df))
        df[col] = df[col] + noise

    # Re-clip to safe bounds
    for col, p in PARAMS.items():
        df[col] = df[col].clip(*p["clip"])

    return df


def generate_normal_data(n):
    """Generate normal sensor readings from observed distributions."""
    data = {
        "ph": np.random.normal(PARAMS["ph"]["mean"], PARAMS["ph"]["std"], n),
        "temperature": np.random.normal(PARAMS["temperature"]["mean"], PARAMS["temperature"]["std"], n),
        "tds": np.random.normal(PARAMS["tds"]["mean"], PARAMS["tds"]["std"], n),
        "turbidity": np.abs(np.random.normal(PARAMS["turbidity"]["mean"], PARAMS["turbidity"]["std"], n)),
    }
    # Clip to realistic bounds
    for col, p in PARAMS.items():
        data[col] = np.clip(data[col], *p["clip"])

    df = pd.DataFrame(data)
    df["is_anomaly"] = 0
    df["timestamp"] = generate_timestamps(n)
    return df


def generate_anomalies(n):
    """
    Generate anomalous readings with realistic failure modes:
    1. pH spikes           — sudden drop to ~4.5 or rise to ~9.5
    2. TDS jumps           — sudden rise to 400+ ppm
    3. Turbidity bursts    — sudden spike to 50+ NTU
    4. Correlated anomalies — TDS + turbidity both high
    5. Gradual drift       — slow creep over 20 readings (hardest for rules)
    """
    records = []
    types = ["ph_spike", "tds_jump", "turb_burst", "correlated", "gradual_drift"]

    # Allocate counts per type
    per_type = n // len(types)
    remainder = n - per_type * len(types)
    counts = [per_type] * len(types)
    counts[0] += remainder  # give remainder to first type

    for atype, count in zip(types, counts):
        for i in range(count):
            # Start with a normal-looking reading
            row = {
                "ph": np.random.normal(7.2, 0.4),
                "temperature": np.random.normal(23.0, 1.5),
                "tds": np.random.normal(108.0, 15.0),
                "turbidity": abs(np.random.normal(2.0, 1.2)),
            }

            if atype == "ph_spike":
                # Sudden pH drop or rise
                if np.random.random() < 0.5:
                    row["ph"] = np.random.uniform(3.5, 5.0)
                else:
                    row["ph"] = np.random.uniform(9.0, 11.0)

            elif atype == "tds_jump":
                row["tds"] = np.random.uniform(400, 800)

            elif atype == "turb_burst":
                row["turbidity"] = np.random.uniform(15, 80)

            elif atype == "correlated":
                # Both TDS and turbidity are elevated together
                row["tds"] = np.random.uniform(350, 600)
                row["turbidity"] = np.random.uniform(8, 30)

            elif atype == "gradual_drift":
                # Simulate a drift — values individually look almost normal
                # but the combination is unusual
                drift_factor = (i + 1) / count  # 0→1 over the batch
                row["ph"] = 7.2 + drift_factor * np.random.choice([-2.5, 2.0])
                row["tds"] = 108 + drift_factor * np.random.uniform(150, 300)
                row["turbidity"] = 2.0 + drift_factor * np.random.uniform(3, 10)

            # Clip to physically possible values
            row["ph"] = np.clip(row["ph"], 0, 14)
            row["temperature"] = np.clip(row["temperature"], 0, 50)
            row["tds"] = np.clip(row["tds"], 0, 1000)
            row["turbidity"] = np.clip(row["turbidity"], 0, 100)

            row["is_anomaly"] = 1
            records.append(row)

    df = pd.DataFrame(records)
    return df


def main():
    print("=" * 60)
    print("Phase 1 — Generating Synthetic Training Data")
    print("=" * 60)

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Generate normal data
    print(f"\n  Generating {N_NORMAL} normal readings...")
    df_normal = generate_normal_data(N_NORMAL)
    df_normal = apply_time_variation(df_normal)

    # Generate anomalies
    print(f"  Generating {N_ANOMALIES} anomalous readings...")
    df_anomalies = generate_anomalies(N_ANOMALIES)

    # Assign timestamps to anomalies (scattered throughout the timeline)
    start_ts = df_normal["timestamp"].min()
    end_ts = df_normal["timestamp"].max()
    total_seconds = (end_ts - start_ts).total_seconds()
    random_offsets = np.sort(np.random.uniform(0, total_seconds, N_ANOMALIES))
    df_anomalies["timestamp"] = [start_ts + timedelta(seconds=s) for s in random_offsets]

    # Combine and sort by timestamp
    df = pd.concat([df_normal, df_anomalies], ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Save
    df.to_csv(OUTPUT_FILE, index=False)

    # Report
    total = len(df)
    n_anom = df["is_anomaly"].sum()
    print(f"\n  ✓ Saved to: {OUTPUT_FILE}")
    print(f"  ✓ Total readings:  {total:,}")
    print(f"  ✓ Normal readings: {total - n_anom:,}")
    print(f"  ✓ Anomalies:       {n_anom:,} ({100*n_anom/total:.1f}%)")
    print(f"\n  Sample statistics:")
    for col in ["ph", "temperature", "tds", "turbidity"]:
        normal_vals = df[df["is_anomaly"] == 0][col]
        print(f"    {col:12s}  mean={normal_vals.mean():.2f}  std={normal_vals.std():.2f}"
              f"  min={normal_vals.min():.2f}  max={normal_vals.max():.2f}")
    print()


if __name__ == "__main__":
    main()
