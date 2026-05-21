#!/bin/bash
set -e

echo "Running migrations..."
python manage.py makemigrations monitor --noinput
python manage.py migrate --noinput

echo "Starting gunicorn..."
exec gunicorn watermonitor.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
