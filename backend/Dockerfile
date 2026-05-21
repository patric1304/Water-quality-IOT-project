FROM python:3.11-slim

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Collect static files (WhiteNoise serves them)
RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "watermonitor.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
