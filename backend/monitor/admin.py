from django.contrib import admin
from .models import SensorReading


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    """Admin interface for viewing and managing sensor readings."""

    list_display = ("timestamp", "ph", "temperature", "tds", "turbidity", "source")
    list_filter = ("source",)
    ordering = ("-timestamp",)
    readonly_fields = ("timestamp",)
