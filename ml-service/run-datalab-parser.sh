#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR

echo "========================================="
echo "Starting DATALAB PARSER worker (CPU)"
echo "Queue: datalab_parse_queue"
echo "Concurrency: 5"
echo "========================================="

# Start Celery worker for datalab_parse_queue with auto-reload
watchmedo auto-restart \
    --directory=$SCRIPT_DIR \
    --pattern='*.py' \
    -- celery -A datalab_worker worker \
    -c 5 \
    --pool=prefork \
    --queues=datalab_parse_queue \
    --hostname=datalab-parser@%h \
    --loglevel=info
