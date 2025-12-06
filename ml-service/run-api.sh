#!/bin/bash

# Database initialization
export PGPASSWORD=$POSTGRES_PASSWORD
DB_EXISTS=$(psql -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$CELERY_DB';")

if [ "$DB_EXISTS" == "1" ]; then
    echo "Database '$CELERY_DB' already exists"
else
    echo "Creating database '$CELERY_DB'..."
    createdb -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" "$CELERY_DB"
    echo "Database '$CELERY_DB' created successfully"
fi

# Start FastAPI only (no Celery, no Jupyter)
echo "Starting FastAPI API server (CPU-only)..."
uvicorn api:app --reload --host 0.0.0.0 --port 8001 --access-log
