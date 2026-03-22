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

# Start Celery worker
exec celery -A $WORKER_MODULE worker \
    -c 1 \
    --pool=solo \
    --queues=convert_queue,synthesize_queue \
    --hostname=converter@%h \
    --loglevel=info \
    --max-tasks-per-child=50
