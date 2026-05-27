"""
ml/export_real_data.py
----------------------
Export real data from the Django API and merge with synthetic data.

Pulls real sensor readings from the live deployment, marks them as non-anomalous,
and merges with the synthetically generated mock data to produce the final
combined training dataset.

Usage:
    python ml/export_real_data.py
"""

import os
import json
import pandas as pd

# Try urllib (stdlib) so we don't need requests as a dependency
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# -- Configuration -------------------------------------------------------------

API_URL = "https://water-monitor-oodh.onrender.com/api/readings/history/?n=500"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
REAL_FILE = os.path.join(DATA_DIR, "real_data.csv")
MOCK_FILE = os.path.join(DATA_DIR, "mock_data.csv")
COMBINED_FILE = os.path.join(DATA_DIR, "combined_data.csv")

TIMEOUT = 30  # seconds


def fetch_real_data():
    """Fetch real sensor readings from the Django API."""
    print(f"  Fetching from: {API_URL}")
    print(f"  (timeout: {TIMEOUT}s — Render free tier may need a cold start)\n")

    try:
        req = Request(API_URL, headers={"Accept": "application/json"})
        resp = urlopen(req, timeout=TIMEOUT)
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        print(f"  OK Received {len(data)} real readings from API")
        return data
    except HTTPError as e:
        print(f"  ERROR HTTP error: {e.code} {e.reason}")
        return None
    except URLError as e:
        print(f"  ERROR Connection error: {e.reason}")
        print("    (Render free tier may be asleep — try again in 60s)")
        return None
    except Exception as e:
        print(f"  ERROR Unexpected error: {e}")
        return None


def process_real_data(data):
    """Convert API JSON response to a DataFrame with is_anomaly=0."""
    df = pd.DataFrame(data)

    # Keep only the columns we need
    cols_keep = ["timestamp", "ph", "temperature", "tds", "turbidity"]
    available = [c for c in cols_keep if c in df.columns]
    df = df[available].copy()

    # Mark all real readings as non-anomalous
    df["is_anomaly"] = 0

    # Convert timestamp to datetime and strip timezone info
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)

    # Drop rows where all sensor values are null
    sensor_cols = [c for c in ["ph", "temperature", "tds", "turbidity"] if c in df.columns]
    df = df.dropna(subset=sensor_cols, how="all")

    return df


def merge_datasets(df_real, df_mock):
    """Merge real and mock datasets into the final combined training set."""
    df = pd.concat([df_mock, df_real], ignore_index=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def main():
    print("=" * 60)
    print("Export Real Data & Merge")
    print("=" * 60)

    os.makedirs(DATA_DIR, exist_ok=True)

    # Check that mock data exists
    if not os.path.exists(MOCK_FILE):
        print(f"\n  ERROR Mock data not found at: {MOCK_FILE}")
        print("    Run 'python ml/generate_mock_data.py' first.")
        return

    df_mock = pd.read_csv(MOCK_FILE, parse_dates=["timestamp"])
    print(f"\n  Loaded mock data: {len(df_mock):,} rows")

    # Fetch real data
    print()
    raw = fetch_real_data()

    if raw and len(raw) > 0:
        df_real = process_real_data(raw)
        df_real.to_csv(REAL_FILE, index=False)
        print(f"  OK Saved real data: {len(df_real):,} rows → {REAL_FILE}")
    else:
        print("\n  ⚠ No real data available — using mock data only.")
        print("    (This is fine for initial training; retrain later with real data)")
        df_real = pd.DataFrame(columns=df_mock.columns)

    # Merge
    df_combined = merge_datasets(df_real, df_mock)
    df_combined.to_csv(COMBINED_FILE, index=False)

    # Report
    n_total = len(df_combined)
    n_real = len(df_real)
    n_mock = len(df_mock)
    n_anom = df_combined["is_anomaly"].sum()

    print(f"\n  OK Combined dataset saved → {COMBINED_FILE}")
    print(f"    Total rows:    {n_total:,}")
    print(f"    Real readings: {n_real:,}")
    print(f"    Mock readings: {n_mock:,}")
    print(f"    Anomalies:     {n_anom:,} ({100*n_anom/n_total:.1f}%)")
    print()


if __name__ == "__main__":
    main()
