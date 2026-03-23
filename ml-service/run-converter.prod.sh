#!/bin/bash
set -e

TTS_ENGINE="${TTS_ENGINE:-kitten}"
if [ "$TTS_ENGINE" = "kitten" ]; then
    WORKER_MODULE="kitten_worker"
else
    WORKER_MODULE="supertonic_worker"
fi

echo "========================================="
echo "Starting CONVERTER worker (production) - Engine: $TTS_ENGINE"
echo "Queues: convert_queue, synthesize_queue"
echo "RabbitMQ Host: ${RABBITMQ_HOST}"
echo "========================================="

# Wait for RabbitMQ on main host
echo "Waiting for RabbitMQ at ${RABBITMQ_HOST}:5672..."
while ! nc -z ${RABBITMQ_HOST} 5672 2>/dev/null; do
    sleep 1
done
echo "RabbitMQ is available"

# Start Celery worker(s)
# KittenTTS uses onnxruntime which isn't fork-safe, so we spin up
# separate solo-pool processes instead of using prefork.
NUM_WORKERS="${CONVERTER_WORKERS:-1}"
if [ "$TTS_ENGINE" = "kitten" ]; then
    NUM_WORKERS="${CONVERTER_WORKERS:-10}"
fi

if [ "$NUM_WORKERS" -eq 1 ]; then
    exec celery -A $WORKER_MODULE worker \
        -c 1 \
        --pool=solo \
        --queues=convert_queue,synthesize_queue \
        --hostname=converter@%h \
        --loglevel=info \
        --max-tasks-per-child=1
else
    echo "Launching $NUM_WORKERS worker processes..."
    PIDS=""
    for i in $(seq 1 $NUM_WORKERS); do
        celery -A $WORKER_MODULE worker \
            -c 1 \
            --pool=solo \
            --queues=convert_queue,synthesize_queue \
            --hostname="converter-${i}@%h" \
            --loglevel=info \
            --max-tasks-per-child=1 &
        PIDS="$PIDS $!"
    done

    # Exit if any worker dies
    trap "kill $PIDS 2>/dev/null; exit 1" SIGTERM SIGINT
    wait -n
    echo "A worker process exited, shutting down..."
    kill $PIDS 2>/dev/null
    exit 1
fi
