#!/bin/bash
set -e

echo "========================================="
echo "Starting FAST PARSER worker (production)"
echo "Queue: fast_parse_queue"
echo "Concurrency: 5"
echo "RabbitMQ Host: ${RABBITMQ_HOST}"
echo "========================================="

# Wait for RabbitMQ
echo "Waiting for RabbitMQ at ${RABBITMQ_HOST}:5672..."
while ! nc -z ${RABBITMQ_HOST} 5672 2>/dev/null; do
    sleep 1
done
echo "RabbitMQ is available"

# Start Celery worker
exec celery -A fast_parser_worker worker \
    -c 5 \
    --pool=prefork \
    --queues=fast_parse_queue \
    --hostname=fast-parser@%h \
    --loglevel=info
