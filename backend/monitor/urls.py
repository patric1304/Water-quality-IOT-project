"""
monitor/urls.py
---------------
URL routes for the monitor app.

Mounted at the root of the project (included from watermonitor/urls.py).
"""

from django.urls import path
from .views import CreateReadingView, LatestReadingView, HistoryView, DashboardView

urlpatterns = [
    # ── REST API ──────────────────────────────────────────────────────────────
    path("api/readings/", CreateReadingView.as_view(), name="create-reading"),
    path("api/readings/latest/", LatestReadingView.as_view(), name="latest-reading"),
    path("api/readings/history/", HistoryView.as_view(), name="reading-history"),

    # ── Dashboard ─────────────────────────────────────────────────────────────
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
]
