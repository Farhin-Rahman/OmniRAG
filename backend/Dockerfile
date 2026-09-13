# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

# Install system dependencies
RUN rm -f /var/lib/apt/lists/lock && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        libpq5 \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        poppler-utils \
        curl \
        build-essential \
        libpq-dev \
        tesseract-ocr \
        tesseract-ocr-ara \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency metadata
COPY requirements-prod.txt ./

# Install python dependencies globally
RUN pip install --upgrade pip && \
    pip install -r requirements-prod.txt

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x /app/backend/entrypoint.sh

# data/ is gitignored (runtime SQLite files, not source) so it never
# arrives via COPY — must exist before the app can create its database
# files there. Locally this is masked by the docker-compose bind mount
# always having a real data/ directory on the host; on a host that
# deploys straight from the image (Render, etc.) there's no such mount.
RUN mkdir -p /app/backend/data && \
    mkdir -p /home/appuser/.cache/huggingface && \
    useradd -m appuser && \
    chown -R appuser:appuser /app/backend /home/appuser

USER appuser

EXPOSE 8080

ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
