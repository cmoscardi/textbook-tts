#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR

echo "========================================="
echo "Starting FAST PARSER worker (CPU)"
echo "Queue: fast_parse_queue"
echo "Concurrency: 3"
echo "========================================="

# Start Celery worker for fast_parse_queue with auto-reload
watchmedo auto-restart \
    --directory=$SCRIPT_DIR \
    --pattern='*.py' \
    -- celery -A fast_parser_worker worker \
    -c 3 \
    --pool=prefork \
    --queues=fast_parse_queue \
    --hostname=fast-parser@%h \
    --loglevel=info
