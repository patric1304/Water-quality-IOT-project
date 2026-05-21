#!/bin/bash
set -e

echo "Running migrations..."
python manage.py makemigrations monitor --noinput
python manage.py migrate --noinput
# python manage.py purge_old_readings --days 0 
# the line above is used to delete all the data in the database, the days param is used to delete data older than N days.


echo "Starting gunicorn..."
exec gunicorn watermonitor.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
