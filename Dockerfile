# Use a slim Python base image
FROM python:3.14-slim-trixie

# Accept build arguments for COS credentials
ARG COS_SECRET_ID
ARG COS_SECRET_KEY

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONIOENCODING=UTF-8 \
    COS_SECRET_ID=${COS_SECRET_ID} \
    COS_SECRET_KEY=${COS_SECRET_KEY}

WORKDIR /app

# Use noninteractive frontend to avoid prompts during build and install ffmpeg
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ffmpeg \
 && rm -rf /var/lib/apt/lists/*

# Copy the rest of the source code
COPY . .

# Install dependencies and the application from pyproject.toml
RUN pip install --upgrade pip \
    && pip install .

# Copy production environment file (create from .env.prod.example if needed)
COPY .env.prod* ./
RUN if [ -f .env.prod ]; then cp .env.prod .env; else echo "Warning: .env.prod not found, using defaults"; fi

# Create logs directory
RUN mkdir -p logs

# Default Port
EXPOSE 9000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

# Run with Uvicorn in production
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-9000} --workers ${WORKERS:-4}"]



