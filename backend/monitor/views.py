"""
monitor/views.py
----------------
API views for sensor readings + dashboard template view.

Endpoints:
  POST   /api/readings/          → CreateReadingView   (API key required)
  GET    /api/readings/latest/   → LatestReadingView   (public)
  GET    /api/readings/history/  → HistoryView         (public)
  GET    /api/readings/anomalies/→ AnomalyListView     (public)
  GET    /api/readings/alerts/   → AlertLogView         (public)
  GET    /dashboard/             → DashboardView       (public)
"""

import logging

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.views.generic import TemplateView

from .models import SensorReading
from .serializers import SensorReadingSerializer
from .authentication import HasValidAPIKey
from .ml_inference import predict_anomaly

from .ml_inference import MODEL_PATH, SCALER_PATH, ML_DIR
import os
from django.http import JsonResponse

def ml_debug(request):
    import onnxruntime as ort
    
    model_exists = os.path.exists(MODEL_PATH)
    shape_info = None
    
    if model_exists:
        try:
            session = ort.InferenceSession(MODEL_PATH)
            inp = session.get_inputs()[0]
            shape_info = f"{inp.name}: {inp.shape}"
        except Exception as e:
            shape_info = f"ERROR: {e}"
    
    return JsonResponse({
        "ml_dir": ML_DIR,
        "model_exists": model_exists,
        "scaler_exists": os.path.exists(SCALER_PATH),
        "ml_dir_contents": os.listdir(ML_DIR) if os.path.isdir(ML_DIR) else "DIR NOT FOUND",
        "onnx_input_shape": shape_info,
    })

logger = logging.getLogger(__name__)

# ── Thresholds (must match Lambda's THRESHOLDS) ──────────────────────────────
THRESHOLDS = {
    "ph":          (6.5, 8.5),
    "temperature": (None, 30.0),
    "tds":         (None, 500.0),
    "turbidity":   (None, 4.0),
}


def _check_thresholds(reading):
    """
    Check if any sensor value exceeds safe thresholds.
    Returns a list of alert strings (empty if all values are safe).
    """
    alerts = []
    for param, (lo, hi) in THRESHOLDS.items():
        value = getattr(reading, param, None)
        if value is None:
            continue
        if lo is not None and value < lo:
            alerts.append(f"{param} is {value} (below minimum {lo})")
        if hi is not None and value > hi:
            alerts.append(f"{param} is {value} (above maximum {hi})")
    return alerts


def _determine_alert_level(threshold_alerts, ml_result):
    """
    Determine alert level using the two-layer decision matrix:

    | Threshold breach | ML anomaly | ML confidence    | Alert level |
    |------------------|------------|------------------|-------------|
    | Yes              | Yes        | high / medium    | CRITICAL    |
    | Yes              | Yes        | low              | WARNING     |
    | Yes              | No         | any              | INFO        |
    | No               | Yes        | high             | WARNING     |
    | No               | Yes        | medium / low     | None        |
    | No               | No         | any              | None        |
    """
    has_threshold_breach = len(threshold_alerts) > 0
    is_anomaly = ml_result.get("is_anomaly", False) if ml_result else False
    confidence = ml_result.get("confidence", "low") if ml_result else "low"

    if has_threshold_breach:
        if is_anomaly and confidence in ("high", "medium"):
            return "CRITICAL"
        elif is_anomaly and confidence == "low":
            return "WARNING"
        else:
            # Threshold breach but ML says normal — likely noise
            return "INFO"
    else:
        if is_anomaly and confidence == "high":
            return "WARNING"
        # ML-only anomaly with medium/low confidence or all normal
        return None


class CreateReadingView(APIView):
    """
    POST /api/readings/

    Called by Lambda every time a new sensor reading arrives from IoT Core.
    Requires a valid API key in the Authorization header.

    After saving the reading:
      1. Fetches recent readings for LSTM sequence input
      2. Runs ML anomaly detection (predict_anomaly)
      3. Determines alert level (threshold + ML gating)
      4. Persists ML and alert fields on the reading
    """

    permission_classes = [HasValidAPIKey]

    def post(self, request):
        serializer = SensorReadingSerializer(data=request.data)
        if serializer.is_valid():
            reading = serializer.save()

            # ── ML Anomaly Detection ─────────────────────────────────────
            try:
                # Fetch recent readings for LSTM sequence (oldest → newest)
                recent_qs = (
                    SensorReading.objects
                    .order_by("-timestamp")[:30]
                )
                recent_list = list(reversed(recent_qs))

                # Build list of dicts for predict_anomaly
                recent_readings = [
                    {
                        "ph": r.ph,
                        "temperature": r.temperature,
                        "tds": r.tds,
                        "turbidity": r.turbidity,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    }
                    for r in recent_list
                ]

                ml_result = predict_anomaly(recent_readings)

                if ml_result:
                    reading.is_anomaly = ml_result["is_anomaly"]
                    reading.anomaly_score = ml_result["anomaly_score"]
                    reading.ml_confidence = ml_result["confidence"]
                    logger.info(
                        "ML inference: anomaly=%s, score=%.6f, confidence=%s",
                        ml_result["is_anomaly"],
                        ml_result["anomaly_score"],
                        ml_result["confidence"],
                    )
                else:
                    logger.info("ML inference returned None (insufficient data or model not loaded)")

            except Exception as e:
                logger.error("ML inference failed in view: %s", e)
                ml_result = None

            # ── Smart Alert Level ────────────────────────────────────────
            threshold_alerts = _check_thresholds(reading)
            alert_level = _determine_alert_level(threshold_alerts, ml_result)
            reading.alert_level = alert_level
            # alert_sent remains False — Lambda handles the actual sending
            reading.save()

            # Return the updated reading with ML + alert fields
            return Response(
                SensorReadingSerializer(reading).data,
                status=status.HTTP_201_CREATED,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LatestReadingView(APIView):
    """
    GET /api/readings/latest/

    Returns the most recent sensor reading as JSON.
    Called by the dashboard JavaScript every 10 seconds.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        reading = SensorReading.objects.first()  # ordered by -timestamp (Meta)
        if reading is None:
            return Response(
                {"detail": "No readings available yet."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = SensorReadingSerializer(reading)
        return Response(serializer.data)


class HistoryView(APIView):
    """
    GET /api/readings/history/?n=60

    Returns the last N sensor readings (default 60) ordered oldest → newest.
    Used by Chart.js to plot rolling line charts on the dashboard.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        n = request.query_params.get("n", 60)
        try:
            n = int(n)
            n = max(1, min(n, 500))  # clamp between 1 and 500
        except (ValueError, TypeError):
            n = 60

        readings = SensorReading.objects.order_by("-timestamp")[:n]
        # Reverse so charts display oldest → newest (left to right)
        readings = list(reversed(readings))
        serializer = SensorReadingSerializer(readings, many=True)
        return Response(serializer.data)


class AnomalyListView(APIView):
    """
    GET /api/readings/anomalies/

    Returns the last 20 readings flagged as anomalous by the ML model.
    Used by the "Recent Anomalies" panel on the dashboard.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        anomalies = SensorReading.objects.filter(
            is_anomaly=True
        ).order_by("-timestamp")[:20]
        serializer = SensorReadingSerializer(anomalies, many=True)
        return Response(serializer.data)


class AlertLogView(APIView):
    """
    GET /api/readings/alerts/

    Returns the last 20 readings that have a non-null alert_level.
    Used by the "Alert Log" panel on the dashboard.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        alerts = SensorReading.objects.filter(
            alert_level__isnull=False
        ).order_by("-timestamp")[:20]
        serializer = SensorReadingSerializer(alerts, many=True)
        return Response(serializer.data)


class DashboardView(TemplateView):
    """
    GET /dashboard/

    Serves the HTML dashboard page. All data is fetched client-side
    via JavaScript calls to the API endpoints above.
    """

    template_name = "monitor/dashboard.html"