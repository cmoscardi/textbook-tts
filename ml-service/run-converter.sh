#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR

echo "========================================="
echo "Starting CONVERTER worker"
echo "GPU allocation: Controlled by NVIDIA_VISIBLE_DEVICES env var"
echo "              (set by start.sh - all/none for dev, specific GPU for prod)"
echo "Queue: convert_queue"
echo "========================================="

# Start Celery worker for convert_queue with auto-reload
watchmedo auto-restart \
    --directory=$SCRIPT_DIR \
    --pattern='*.py' \
    -- celery -A ml_worker worker \
    -c 1 \
    --pool=solo \
    --queues=convert_queue \
    --hostname=converter@%h \
    --loglevel=info
