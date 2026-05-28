"""
monitor/models.py
-----------------
SensorReading model — stores one reading from the Pi sensor array.

Fields match the JSON payload format defined in PROJECT_CONTEXT.md:
  { "ph": 7.2, "temperature": null, "tds": 340.5, "turbidity": 1.8, "timestamp": "..." }

The 'source' field defaults to the DEVICE_SOURCE env var (default "pi-01").
"""

from django.db import models
from django.conf import settings


class SensorReading(models.Model):
    """A single sensor reading from the Raspberry Pi."""

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text="UTC timestamp when the reading was recorded.",
    )
    ph = models.FloatField(
        null=True,
        blank=True,
        help_text="pH value (0–14 scale).",
    )
    temperature = models.FloatField(
        null=True,
        blank=True,
        help_text="Water temperature in °C.",
    )
    tds = models.FloatField(
        null=True,
        blank=True,
        help_text="Total dissolved solids in mg/L.",
    )
    turbidity = models.FloatField(
        null=True,
        blank=True,
        help_text="Turbidity in NTU.",
    )
    source = models.CharField(
        max_length=50,
        default=getattr(settings, "DEVICE_SOURCE", "pi-01"),
        help_text="Device identifier (e.g. 'pi-01').",
    )

    # ── ML Anomaly Detection fields (populated by predict_anomaly) ────────
    is_anomaly = models.BooleanField(
        null=True,
        blank=True,
        help_text="True if the ML model flagged this reading as anomalous.",
    )
    anomaly_score = models.FloatField(
        null=True,
        blank=True,
        help_text="ML reconstruction error score (higher = more anomalous).",
    )
    ml_confidence = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="ML confidence level: 'high', 'medium', or 'low'.",
    )
    is_anomaly_ph = models.BooleanField(
        default=False,
        help_text="True if the ML model flagged pH as anomalous.",
    )
    is_anomaly_temp = models.BooleanField(
        default=False,
        help_text="True if the ML model flagged temperature as anomalous.",
    )
    is_anomaly_tds = models.BooleanField(
        default=False,
        help_text="True if the ML model flagged TDS as anomalous.",
    )
    is_anomaly_turb = models.BooleanField(
        default=False,
        help_text="True if the ML model flagged turbidity as anomalous.",
    )

    # ── Smart Alerting fields (determined by threshold + ML gating) ───────
    alert_level = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        choices=[
            ("CRITICAL", "Critical"),
            ("WARNING", "Warning"),
            ("INFO", "Info"),
        ],
        help_text="Alert severity: CRITICAL, WARNING, or INFO.",
    )
    alert_sent = models.BooleanField(
        default=False,
        help_text="Whether an SNS notification was sent for this reading.",
    )

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Sensor Reading"
        verbose_name_plural = "Sensor Readings"

    def __str__(self):
        return (
            f"Reading @ {self.timestamp:%Y-%m-%d %H:%M:%S} — "
            f"pH={self.ph}, T={self.temperature}°C, "
            f"TDS={self.tds}mg/L, Turb={self.turbidity}NTU"
        )
