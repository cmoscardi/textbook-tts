#!/bin/bash
#

#./install.sh

uvicorn api:app --reload --host 0.0.0.0 --port 8001 --access-log &


SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

cd $SCRIPT_DIR

export PGPASSWORD=$POSTGRES_PASSWORD
# Check if the database exists
DB_EXISTS=$(psql -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$CELERY_DB';")

if [ "$DB_EXISTS" == "1" ]; then
    echo "Database '$CELERY_DB' already exists"
else
    echo "Creating database '$CELERY_DB'..."
    createdb -U "$POSTGRES_USER" -h "$POSTGRES_HOST" -p "5432" "$CELERY_DB"
    echo "Database '$CELERY_DB' created successfully"
fi

echo "and were moving along to run jupyterlab?"

# password is lizard
jupyter lab --ip=0.0.0.0 --allow-root --ServerApp.password='argon2:$argon2id$v=19$m=10240,t=10,p=8$X7+Dr0XggW22erD5JuwdJA$8JKWkBqLP9jIHCbsrq9HVkkS2qyVOx08OltS9Cq2dus' &

# Start main worker for non-OCR tasks
watchmedo auto-restart --directory=$SCRIPT_DIR --pattern='*.py' -- celery -A ml_worker worker -c 1 --pool=solo  --loglevel=info
