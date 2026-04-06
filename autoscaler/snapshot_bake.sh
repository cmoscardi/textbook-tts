#!/bin/bash
set -e

# Bake a DigitalOcean snapshot with Docker and pre-built worker images.
# Run this script from the repo root whenever worker code or dependencies change.
#
# Prerequisites:
#   - DIGITALOCEAN_API_TOKEN set in environment
#   - doctl CLI installed (brew install doctl / snap install doctl)
#   - SSH key registered with DO (DO_SSH_KEY_FINGERPRINT in .env.production)
#
# Usage:
#   source .env.production
#   ./autoscaler/snapshot_bake.sh

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

REGION="${DO_REGION:-nyc3}"
SIZE="s-2vcpu-4gb"  # Larger for building images, snapshot is size-independent
BASE_IMAGE="ubuntu-24-04-x64"
DROPLET_NAME="snapshot-bake-$(date +%s)"
SNAPSHOT_NAME="autoscaler-workers-$(date +%Y%m%d-%H%M%S)"

if [ -z "$DIGITALOCEAN_API_TOKEN" ]; then
    echo -e "${RED}Error: DIGITALOCEAN_API_TOKEN not set${NC}"
    exit 1
fi

echo -e "${GREEN}Step 1: Creating temporary droplet for baking...${NC}"
DROPLET_ID=$(doctl compute droplet create "$DROPLET_NAME" \
    --region "$REGION" \
    --size "$SIZE" \
    --image "$BASE_IMAGE" \
    --ssh-keys "${DO_SSH_KEY_FINGERPRINT}" \
    --wait \
    --format ID \
    --no-header)

echo "Droplet created: $DROPLET_ID"

# Get IP
DROPLET_IP=$(doctl compute droplet get "$DROPLET_ID" --format PublicIPv4 --no-header)
echo "Droplet IP: $DROPLET_IP"

# Wait for SSH
echo "Waiting for SSH..."
for i in $(seq 1 30); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@"$DROPLET_IP" "echo ok" 2>/dev/null; then
        break
    fi
    sleep 5
done

echo -e "${GREEN}Step 2: Installing Docker on droplet...${NC}"
ssh root@"$DROPLET_IP" <<'REMOTE_SCRIPT'
set -e
apt-get update -qq
apt-get install -y -qq docker.io
systemctl enable docker
systemctl start docker

# Create worker startup script directory
mkdir -p /opt/autoscaler
REMOTE_SCRIPT

echo -e "${GREEN}Step 3: Copying worker code to droplet...${NC}"
rsync -az --progress \
    ./ml-service/ \
    root@"$DROPLET_IP":/opt/autoscaler/ml-service/ \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git'

echo -e "${GREEN}Step 4: Building Docker images on droplet...${NC}"
# Use TTS_DOCKERFILE from environment (set in .env.production, e.g. Dockerfile.supertonic)
CONVERTER_DOCKERFILE="${TTS_DOCKERFILE:-Dockerfile.kitten}"
echo "Converter Dockerfile: $CONVERTER_DOCKERFILE (TTS_ENGINE=${TTS_ENGINE:-kitten})"

ssh root@"$DROPLET_IP" "set -e && cd /opt/autoscaler/ml-service && \
    echo 'Building fast-parser image...' && \
    docker build -f Dockerfile.fast-parser -t fast-parser:latest . && \
    echo 'Building datalab-parser image...' && \
    docker build -f Dockerfile.datalab -t datalab-parser:latest . && \
    echo 'Building converter image ($CONVERTER_DOCKERFILE)...' && \
    docker build -f $CONVERTER_DOCKERFILE -t converter:latest ."

echo -e "${GREEN}Step 5: Writing startup script...${NC}"
ssh root@"$DROPLET_IP" <<'REMOTE_SCRIPT'
cat > /opt/autoscaler/start-worker.sh <<'STARTUP'
#!/bin/bash
set -e

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
STARTUP

chmod +x /opt/autoscaler/start-worker.sh
REMOTE_SCRIPT

echo -e "${GREEN}Step 6: Creating snapshot...${NC}"
# Power off before snapshot for consistency
doctl compute droplet-action power-off "$DROPLET_ID" --wait

SNAPSHOT_ID=$(doctl compute droplet-action snapshot "$DROPLET_ID" \
    --snapshot-name "$SNAPSHOT_NAME" \
    --wait \
    --format ID \
    --no-header)

echo -e "${GREEN}Step 7: Cleaning up temporary droplet...${NC}"
doctl compute droplet delete "$DROPLET_ID" --force

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Snapshot baked successfully!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Snapshot name: $SNAPSHOT_NAME"
echo "Snapshot action ID: $SNAPSHOT_ID"
echo ""
echo "To get the snapshot ID, run:"
echo "  doctl compute snapshot list --format ID,Name | grep $SNAPSHOT_NAME"
echo ""
echo "Then update .env.production:"
echo "  DO_FAST_PARSER_SNAPSHOT_ID=<snapshot-id>"
echo "  DO_DATALAB_PARSER_SNAPSHOT_ID=<snapshot-id>"
echo "  DO_CONVERTER_SNAPSHOT_ID=<snapshot-id>"
echo ""
echo "(All three use the same snapshot — the WORKER_TYPE env var selects the image at boot)"
