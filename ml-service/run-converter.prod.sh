#!/bin/bash
set -e

echo "========================================="
echo "Starting CONVERTER worker (production)"
echo "GPU: ${NVIDIA_VISIBLE_DEVICES}"
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
exec celery -A supertonic_worker worker \
    -c 1 \
    --pool=solo \
    --queues=convert_queue,synthesize_queue \
    --hostname=converter@%h \
    --loglevel=info \
    --max-tasks-per-child=50
