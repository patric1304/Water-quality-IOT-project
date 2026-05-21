"""
monitor/views.py
----------------
API views for sensor readings + dashboard template view.

Endpoints:
  POST   /api/readings/          → CreateReadingView   (API key required)
  GET    /api/readings/latest/   → LatestReadingView   (public)
  GET    /api/readings/history/  → HistoryView         (public)
  GET    /dashboard/             → DashboardView       (public)
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.views.generic import TemplateView

from .models import SensorReading
from .serializers import SensorReadingSerializer
from .authentication import HasValidAPIKey


class CreateReadingView(APIView):
    """
    POST /api/readings/

    Called by Lambda every time a new sensor reading arrives from IoT Core.
    Requires a valid API key in the Authorization header.
    """

    permission_classes = [HasValidAPIKey]

    def post(self, request):
        serializer = SensorReadingSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
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


class DashboardView(TemplateView):
    """
    GET /dashboard/

    Serves the HTML dashboard page. All data is fetched client-side
    via JavaScript calls to the API endpoints above.
    """

    template_name = "monitor/dashboard.html"
