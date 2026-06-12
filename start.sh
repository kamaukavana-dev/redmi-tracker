#!/bin/sh
# Startup script for Railway deployment
# Runs migrations and starts the application

set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT