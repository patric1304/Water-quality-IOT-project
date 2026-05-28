from django.urls import path
from .views import (
    CreateReadingView,
    LatestReadingView,
    HistoryView,
    AnomalyListView,
    AlertLogView,
    DashboardView,
    ml_debug,
)

urlpatterns = [
    # ── REST API ──────────────────────────────────────────────────────────────
    path("api/readings/", CreateReadingView.as_view(), name="create-reading"),
    path("api/readings/latest/", LatestReadingView.as_view(), name="latest-reading"),
    path("api/readings/history/", HistoryView.as_view(), name="reading-history"),
    path("api/readings/anomalies/", AnomalyListView.as_view(), name="anomaly-list"),
    path("api/readings/alerts/", AlertLogView.as_view(), name="alert-log"),

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("dashboard/", DashboardView.as_view(), name="dashboard"),

    # ── Temporary ML debug ────────────────────────────────────────────────────
    path("ml-debug/", ml_debug, name="ml-debug"),
]