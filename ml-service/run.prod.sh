#!/bin/bash
set -e

echo "Starting ML Service in production mode..."

# Database initialization
export PGPASSWORD=$POSTGRES_PASSWORD

# Check if the database exists
DB_EXISTS=$(psql -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$CELERY_DB';")

if [ "$DB_EXISTS" == "1" ]; then
    echo "Database '$CELERY_DB' already exists"
else
    echo "Creating database '$CELERY_DB'..."
    createdb -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" "$CELERY_DB"
    echo "Database '$CELERY_DB' created successfully"
fi

# Start FastAPI with Gunicorn for production
echo "Starting FastAPI API server with Gunicorn..."
gunicorn api:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8001 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info &

API_PID=$!

# Start Celery worker
echo "Starting Celery worker..."
celery -A ml_worker worker \
    -c 1 \
    --loglevel=info \
    --max-tasks-per-child=1 &

CELERY_PID=$!

# Function to handle shutdown
shutdown() {
    echo "Shutting down services..."
    kill $API_PID 2>/dev/null || true
    kill $CELERY_PID 2>/dev/null || true
    wait
    echo "Services stopped"
    exit 0
}

# Trap signals for graceful shutdown
trap shutdown SIGTERM SIGINT

# Wait for both processes
wait $API_PID $CELERY_PID
