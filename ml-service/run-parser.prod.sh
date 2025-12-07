#!/bin/bash
set -e

echo "========================================="
echo "Starting PARSER worker (production)"
echo "GPU: ${NVIDIA_VISIBLE_DEVICES}"
echo "Queue: parse_queue"
echo "========================================="

# Wait for RabbitMQ
echo "Waiting for RabbitMQ..."
while ! nc -z ${RABBITMQ_HOST:-rabbitmq-prod} 5672 2>/dev/null; do
    sleep 1
done
echo "RabbitMQ is available"

# Start Celery worker
exec celery -A ml_worker worker \
    -c 1 \
    --pool=solo \
    --queues=parse_queue \
    --hostname=parser@%h \
    --loglevel=info \
    --max-tasks-per-child=1
