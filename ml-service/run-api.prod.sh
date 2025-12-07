#!/bin/bash
set -e

echo "Starting ML API in production mode..."

# Database initialization (Celery DB)
export PGPASSWORD=$POSTGRES_PASSWORD
DB_EXISTS=$(psql -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$CELERY_DB';" 2>/dev/null || echo "0")

if [ "$DB_EXISTS" != "1" ]; then
    echo "Creating database '$CELERY_DB'..."
    createdb -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" "$CELERY_DB" 2>/dev/null || true
fi

# Start FastAPI with Gunicorn
exec gunicorn api:app \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8001 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
