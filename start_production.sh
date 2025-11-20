#!/bin/bash

# Production startup script for CapCut API

set -e

echo "Starting CapCut API in production mode..."

# Load environment variables if .env exists
if [ -f .env ]; then
    echo "Loading environment variables from .env"
    export $(cat .env | grep -v '^#' | xargs)
fi

# Set default values
export PORT=${PORT:-9000}
export WORKERS=${WORKERS:-1}
export LOG_LEVEL=${LOG_LEVEL:-info}

# Create logs directory
mkdir -p logs

# Start Uvicorn
echo "Starting Uvicorn with $WORKERS workers on port $PORT"
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --workers $WORKERS \
    --log-level $LOG_LEVEL
