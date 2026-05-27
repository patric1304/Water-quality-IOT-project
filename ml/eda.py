"""
ml/eda.py
---------
Exploratory Data Analysis.

Generates publication-ready plots for the project report:
  1. Sensor distributions (histogram + KDE)
  2. Correlation heatmap
  3. Time series with anomaly highlights
  4. Pairwise anomaly scatter plots

Also prints summary statistics to the console.

Usage:
    python ml/eda.py
"""

import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # non-interactive backend for saving plots
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# -- Configuration -------------------------------------------------------------

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
PLOT_DIR = os.path.join(os.path.dirname(__file__), "plots")
COMBINED_FILE = os.path.join(DATA_DIR, "combined_data.csv")

SENSOR_COLS = ["ph", "temperature", "tds", "turbidity"]
SENSOR_LABELS = {
    "ph": "pH Level",
    "temperature": "Temperature (°C)",
    "tds": "TDS (mg/L)",
    "turbidity": "Turbidity (NTU)",
}
SENSOR_COLORS = {
    "ph": "#3b82f6",
    "temperature": "#f59e0b",
    "tds": "#8b5cf6",
    "turbidity": "#10b981",
}

# Plot style
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
})


def load_data():
    """Load the combined dataset."""
    if not os.path.exists(COMBINED_FILE):
        print(f"  ERROR Combined data not found: {COMBINED_FILE}")
        print("    Run Phase 1 and 2 first.")
        return None
    df = pd.read_csv(COMBINED_FILE, parse_dates=["timestamp"])
    return df


def print_statistics(df):
    """Print summary statistics to the console."""
    print("\n  Summary Statistics (Normal readings only)")
    print("  " + "-" * 56)

    normal = df[df["is_anomaly"] == 0]
    stats = normal[SENSOR_COLS].describe(percentiles=[0.05, 0.25, 0.5, 0.75, 0.95])
    print(stats.to_string())

    print(f"\n  Dataset composition:")
    print(f"    Total:     {len(df):,}")
    print(f"    Normal:    {len(normal):,}")
    print(f"    Anomalies: {(df['is_anomaly'] == 1).sum():,}")

    # Correlation matrix (printed)
    print(f"\n  Correlation matrix (normal data):")
    corr = normal[SENSOR_COLS].corr()
    print(corr.round(3).to_string())


def plot_distributions(df):
    """Plot 1: Histogram + KDE for each sensor parameter."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.suptitle("Sensor Value Distributions", fontsize=16, fontweight="bold", y=0.98)

    normal = df[df["is_anomaly"] == 0]
    anomaly = df[df["is_anomaly"] == 1]

    for ax, col in zip(axes.flat, SENSOR_COLS):
        # Normal distribution
        ax.hist(normal[col].dropna(), bins=50, alpha=0.6,
                color=SENSOR_COLORS[col], label="Normal", density=True, edgecolor="white")
        # Anomaly distribution
        if len(anomaly) > 0:
            ax.hist(anomaly[col].dropna(), bins=30, alpha=0.4,
                    color="#ef4444", label="Anomaly", density=True, edgecolor="white")

        # KDE overlay for normal
        try:
            normal[col].dropna().plot.kde(ax=ax, color=SENSOR_COLORS[col],
                                           linewidth=2, label="_kde")
        except Exception:
            pass

        ax.set_title(SENSOR_LABELS[col], fontweight="600")
        ax.set_xlabel(SENSOR_LABELS[col])
        ax.set_ylabel("Density")
        ax.legend(fontsize=9)
        ax.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    path = os.path.join(PLOT_DIR, "distributions.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  OK Saved: {path}")


def plot_correlation(df):
    """Plot 2: Correlation heatmap."""
    normal = df[df["is_anomaly"] == 0]
    corr = normal[SENSOR_COLS].corr()

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(corr, annot=True, fmt=".3f", cmap="coolwarm", center=0,
                square=True, linewidths=1, linecolor="white",
                xticklabels=[SENSOR_LABELS[c] for c in SENSOR_COLS],
                yticklabels=[SENSOR_LABELS[c] for c in SENSOR_COLS],
                ax=ax, vmin=-1, vmax=1,
                annot_kws={"size": 12, "fontweight": "bold"})
    ax.set_title("Sensor Correlation Matrix (Normal Readings)", fontsize=14, fontweight="bold", pad=15)

    plt.tight_layout()
    path = os.path.join(PLOT_DIR, "correlation_heatmap.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  OK Saved: {path}")


def plot_time_series(df):
    """Plot 3: Time series of all parameters with anomalies highlighted."""
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    fig.suptitle("Sensor Time Series with Anomaly Highlights",
                 fontsize=16, fontweight="bold", y=0.98)

    normal = df[df["is_anomaly"] == 0]
    anomaly = df[df["is_anomaly"] == 1]

    for ax, col in zip(axes, SENSOR_COLS):
        # Plot normal readings
        ax.plot(normal["timestamp"], normal[col], color=SENSOR_COLORS[col],
                alpha=0.5, linewidth=0.5, label="Normal")
        # Highlight anomalies
        if len(anomaly) > 0:
            ax.scatter(anomaly["timestamp"], anomaly[col], color="#ef4444",
                       s=12, alpha=0.8, zorder=5, label="Anomaly", marker="x")

        ax.set_ylabel(SENSOR_LABELS[col], fontsize=10)
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("Time")
    # Format x-axis dates
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator())

    plt.tight_layout()
    path = os.path.join(PLOT_DIR, "time_series.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  OK Saved: {path}")


def plot_anomaly_scatter(df):
    """Plot 4: Pairwise scatter plots colored by anomaly label."""
    pairs = [
        ("ph", "tds"),
        ("ph", "turbidity"),
        ("tds", "turbidity"),
        ("temperature", "tds"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 10))
    fig.suptitle("Pairwise Scatter — Normal vs Anomalous",
                 fontsize=16, fontweight="bold", y=0.98)

    normal = df[df["is_anomaly"] == 0]
    anomaly = df[df["is_anomaly"] == 1]

    for ax, (x_col, y_col) in zip(axes.flat, pairs):
        ax.scatter(normal[x_col], normal[y_col], c=SENSOR_COLORS[x_col],
                   alpha=0.15, s=8, label="Normal")
        if len(anomaly) > 0:
            ax.scatter(anomaly[x_col], anomaly[y_col], c="#ef4444",
                       alpha=0.7, s=20, marker="x", label="Anomaly", zorder=5)
        ax.set_xlabel(SENSOR_LABELS[x_col])
        ax.set_ylabel(SENSOR_LABELS[y_col])
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(alpha=0.3)

    plt.tight_layout()
    path = os.path.join(PLOT_DIR, "anomaly_scatter.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  OK Saved: {path}")


def main():
    print("=" * 60)
    print("Exploratory Data Analysis")
    print("=" * 60)

    os.makedirs(PLOT_DIR, exist_ok=True)

    df = load_data()
    if df is None:
        return

    print(f"\n  Loaded {len(df):,} readings from combined dataset")
    print_statistics(df)

    print(f"\n  Generating plots...")
    plot_distributions(df)
    plot_correlation(df)
    plot_time_series(df)
    plot_anomaly_scatter(df)

    print(f"\n  All plots saved to: {PLOT_DIR}")
    print()


if __name__ == "__main__":
    main()
