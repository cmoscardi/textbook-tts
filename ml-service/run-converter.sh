#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR

echo "========================================="
echo "Starting CONVERTER worker (CPU)"
echo "Queues: convert_queue, synthesize_queue"
echo "========================================="

# Start Celery worker for convert_queue with auto-reload
watchmedo auto-restart \
    --directory=$SCRIPT_DIR \
    --pattern='*.py' \
    -- celery -A supertonic_worker worker \
    -c 1 \
    --pool=solo \
    --queues=convert_queue,synthesize_queue \
    --hostname=converter@%h \
    --loglevel=info
