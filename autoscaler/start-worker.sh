#!/bin/bash
set -e

# Worker bootstrap for autoscaler DO droplets.
#
# Baked into the snapshot at /opt/autoscaler/start-worker.sh by autoscaler/snapshot_bake.sh,
# and invoked at boot by cloud-init (see autoscaler/autoscaler.py:_make_user_data). It reads
# WORKER_TYPE (and the rest of the config) from /etc/environment and launches the matching
# worker image as a container named `worker`.

# Source environment
set -a; source /etc/environment; set +a

WORKER_TYPE="${WORKER_TYPE:-fast-parser}"
echo "Starting worker: $WORKER_TYPE"

case "$WORKER_TYPE" in
    fast-parser)
        docker run -d --restart=unless-stopped \
            --name worker \
            -e RABBITMQ_HOST="$RABBITMQ_HOST" \
            -e RABBITMQ_USER="$RABBITMQ_USER" \
            -e RABBITMQ_PASS="$RABBITMQ_PASS" \
            -e DATABASE_CELERY_URL="$DATABASE_CELERY_URL" \
            -e SUPABASE_URL="$SUPABASE_URL" \
            -e SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
            fast-parser:latest \
            ./run-fast-parser.prod.sh
        ;;
    datalab-parser)
        docker run -d --restart=unless-stopped \
            --name worker \
            -e RABBITMQ_HOST="$RABBITMQ_HOST" \
            -e RABBITMQ_USER="$RABBITMQ_USER" \
            -e RABBITMQ_PASS="$RABBITMQ_PASS" \
            -e DATABASE_CELERY_URL="$DATABASE_CELERY_URL" \
            -e SUPABASE_URL="$SUPABASE_URL" \
            -e SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
            -e DATALAB_API_KEY="$DATALAB_API_KEY" \
            datalab-parser:latest \
            ./run-datalab-parser.prod.sh
        ;;
    converter)
        docker run -d --restart=unless-stopped \
            --name worker \
            -v /opt/autoscaler/ml-service:/app \
            -w /app \
            -e RABBITMQ_HOST="$RABBITMQ_HOST" \
            -e RABBITMQ_USER="$RABBITMQ_USER" \
            -e RABBITMQ_PASS="$RABBITMQ_PASS" \
            -e DATABASE_CELERY_URL="$DATABASE_CELERY_URL" \
            -e SUPABASE_URL="$SUPABASE_URL" \
            -e SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
            -e TTS_ENGINE="$TTS_ENGINE" \
            -e CONVERTER_WORKERS="${CONVERTER_WORKERS:-5}" \
            converter:latest \
            ./run-converter.prod.sh
        ;;
    *)
        echo "Unknown worker type: $WORKER_TYPE"
        exit 1
        ;;
esac

echo "Worker $WORKER_TYPE started"
