#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR

TTS_ENGINE="${TTS_ENGINE:-kitten}"
if [ "$TTS_ENGINE" = "kitten" ]; then
    WORKER_MODULE="kitten_worker"
else
    WORKER_MODULE="supertonic_worker"
fi

echo "========================================="
echo "Starting CONVERTER worker (CPU) - Engine: $TTS_ENGINE"
echo "Queues: convert_queue, synthesize_queue"
echo "========================================="

# Start Celery worker for convert_queue with auto-reload
watchmedo auto-restart \
    --directory=$SCRIPT_DIR \
    --pattern='*.py' \
    -- celery -A $WORKER_MODULE worker \
    -c 1 \
    --pool=solo \
    --queues=convert_queue,synthesize_queue \
    --hostname=converter@%h \
    --loglevel=info
