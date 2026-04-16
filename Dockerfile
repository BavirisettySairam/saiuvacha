FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source — bump the comment below to force a full rebuild when Railway caches stale layers
# cache-bust: v2
COPY . .

# Collect static files — SECRET_KEY must be set for Django to start,
# but the actual value doesn't matter at build time (only used at runtime).
RUN SECRET_KEY=build-time-placeholder \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    DATABASE_URL=sqlite:///tmp/build.db \
    python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["sh", "-c", "exec gunicorn config.asgi:application --worker-class uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:${PORT:-8000} --timeout 120 --keep-alive 75"]
