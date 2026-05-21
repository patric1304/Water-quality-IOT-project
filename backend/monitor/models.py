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
