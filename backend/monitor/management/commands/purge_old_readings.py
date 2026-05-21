"""
management/commands/purge_old_readings.py
-----------------------------------------
Deletes SensorReading rows older than N days to prevent the free-tier
PostgreSQL database (1 GB) from filling up.

Usage:
  python manage.py purge_old_readings              # default: keep last 30 days
  python manage.py purge_old_readings --days 7      # keep last 7 days
  python manage.py purge_old_readings --days 0      # delete ALL readings
  python manage.py purge_old_readings --dry-run     # show what would be deleted
"""

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from monitor.models import SensorReading


class Command(BaseCommand):
    help = "Delete sensor readings older than N days (default 30). Use --days 0 to delete all."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Keep readings from the last N days. Older ones are deleted. (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many readings would be deleted without actually deleting.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]

        if days == 0:
            old_readings = SensorReading.objects.all()
        else:
            cutoff = timezone.now() - timedelta(days=days)
            old_readings = SensorReading.objects.filter(timestamp__lt=cutoff)

        count = old_readings.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No readings to delete."))
            return

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"[DRY RUN] Would delete {count} readings."
            ))
            return

        old_readings.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} readings."))
