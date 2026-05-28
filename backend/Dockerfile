FROM python:3.11-slim

# Prevent Python from writing .pyc and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend project files
COPY backend/ .

# Copy ML model files and feature engineering from repo root
COPY ml/ /app/ml/

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Collect static files (WhiteNoise serves them)
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Entrypoint runs migrations then starts gunicorn
CMD ["./entrypoint.sh"]
