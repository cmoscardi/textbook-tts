#!/bin/bash
set -e

REMOTE_USER="christian"
REMOTE_HOST="192.168.1.15"
REMOTE_DIR="~/textbook-tts"
MAIN_HOST_TUN0="10.8.0.10"

echo "============================================"
echo "Production Deployment - Multi-GPU Setup"
echo "============================================"
echo "Main Host (tun0): ${MAIN_HOST_TUN0}"
echo "Remote Host: ${REMOTE_HOST}"
echo ""

# Step 1: Create docker context if not exists
echo "=== Setting up Docker context ==="
docker context inspect remote-gpu >/dev/null 2>&1 || \
    docker context create remote-gpu --docker "host=ssh://${REMOTE_USER}@${REMOTE_HOST}"

# Step 2: Deploy to Main Host
echo ""
echo "=== Deploying to Main Host ==="
docker compose -f docker-compose.prod.yml build ml-api parser
docker compose -f docker-compose.prod.yml up -d rabbitmq
echo "Waiting for RabbitMQ to be healthy..."
sleep 10
docker compose -f docker-compose.prod.yml up -d ml-api parser

# Step 3: Sync files to Remote Host
echo ""
echo "=== Syncing files to Remote Host ==="
ssh ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_DIR}/ml-service ${REMOTE_DIR}/hf-cache ${REMOTE_DIR}/dl-cache"

rsync -avz --progress \
    ./ml-service/ \
    ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/ml-service/ \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git'

rsync -avz .env.production ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/
rsync -avz docker-compose.remote.yml ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/

# Step 4: Build and deploy on Remote Host
echo ""
echo "=== Deploying Converter to Remote Host ==="
docker --context remote-gpu compose -f ${REMOTE_DIR}/docker-compose.remote.yml build
docker --context remote-gpu compose -f ${REMOTE_DIR}/docker-compose.remote.yml up -d

echo ""
echo "============================================"
echo "Deployment Complete!"
echo "============================================"
echo ""
echo "Services running:"
echo "  Main Host:"
echo "    - ml-api-prod     (port 8001)"
echo "    - parser-prod     (GPU 0, parse_queue)"
echo "    - rabbitmq-prod   (port 5672 on ${MAIN_HOST_TUN0})"
echo ""
echo "  Remote Host (${REMOTE_HOST}):"
echo "    - converter-prod  (GPU, convert_queue)"
echo ""
echo "To check logs:"
echo "  docker logs -f ml-api-prod"
echo "  docker logs -f parser-prod"
echo "  docker --context remote-gpu logs -f converter-prod"
