"""
watermonitor URL Configuration

Routes:
  /admin/          → Django admin
  /api/            → REST API (monitor app)
  /dashboard/      → Live dashboard page
"""

from django.contrib import admin
from django.urls import path, include, re_path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("monitor.urls")),

    # Catch-all: redirect any unknown URL to /dashboard/
    re_path(r"^.*$", RedirectView.as_view(url="/dashboard/", permanent=False)),
]
