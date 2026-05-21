"""
watermonitor URL Configuration

Routes:
  /admin/          → Django admin
  /api/            → REST API (monitor app)
  /dashboard/      → Live dashboard page
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("monitor.urls")),
]
