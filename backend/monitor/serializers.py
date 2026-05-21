"""
monitor/serializers.py
----------------------
DRF serializers for the SensorReading model.

SensorReadingSerializer handles both:
  - Incoming POSTs from Lambda (create)
  - Outgoing GETs for the dashboard (read)
"""

from rest_framework import serializers
from .models import SensorReading


class SensorReadingSerializer(serializers.ModelSerializer):
    """
    Serializes SensorReading instances.

    On creation (POST from Lambda):
      - timestamp is optional — auto-set by the model if not provided.
      - source is optional — defaults to DEVICE_SOURCE setting.
      - All sensor fields (ph, temperature, tds, turbidity) are optional/nullable.

    On read (GET for dashboard):
      - Returns all fields including the auto-generated id and timestamp.
    """

    class Meta:
        model = SensorReading
        fields = ["id", "timestamp", "ph", "temperature", "tds", "turbidity", "source"]
        read_only_fields = ["id"]
        extra_kwargs = {
            "timestamp": {"required": False},
            "source": {"required": False},
        }
