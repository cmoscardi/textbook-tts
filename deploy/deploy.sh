#!/bin/bash
set -e

# Production deployment script for ML Service and RabbitMQ
# Multi-host deployment: Main host + Remote GPU host
# Usage: ./deploy/deploy.sh

echo "========================================="
echo "ML Service Production Deployment"
echo "Multi-GPU Setup (Main + Remote Host)"
echo "========================================="

# Parse flags
BUILD_CACHE_FLAG="--no-cache"
while getopts "c" opt; do
    case $opt in
        c) BUILD_CACHE_FLAG="" ;;
        *) echo "Usage: $0 [-c]" && exit 1 ;;
    esac
done

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# TTS Engine configuration (kitten or supertonic)
export TTS_ENGINE="${TTS_ENGINE:-kitten}"
export TTS_DOCKERFILE="${TTS_DOCKERFILE:-Dockerfile.kitten}"

# Multi-host configuration
REMOTE_USER="christian"
REMOTE_HOST="loc"
REMOTE_DIR="~/textbook-tts-worker"

# Detect tun0 IP address dynamically
#MAIN_HOST_TUN0=$(ip -4 addr show tun0 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -n1)
MAIN_HOST_TUN0=rabbitmq-prod

if [ -z "$MAIN_HOST_TUN0" ]; then
    echo -e "${RED}Error: Could not detect tun0 interface IP address!${NC}"
    echo "Make sure the tun0 interface is up and configured."
    exit 1
fi

echo "Detected tun0 IP: $MAIN_HOST_TUN0"
export MAIN_HOST_TUN0

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
REMOTE_COMPOSE_FILE="docker-compose.remote.yml"
ENV_FILE=".env.production"

# Check if running on the server
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}Error: $ENV_FILE not found!${NC}"
    echo "Please copy .env.production.example to .env.production and configure it."
    exit 1
fi

# Check for NVIDIA Docker runtime
if ! docker info | grep -q "nvidia"; then
    echo -e "${YELLOW}Warning: NVIDIA Docker runtime not detected!${NC}"
    echo "Make sure nvidia-docker is installed for GPU support."
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}Step 1: Pulling latest code...${NC}"
git pull origin main || {
    echo -e "${YELLOW}Warning: Could not pull from git. Continuing with local code...${NC}"
}

echo -e "${GREEN}Step 2: Loading and validating Supabase environment...${NC}"
# Source environment variables
set -a
source "$ENV_FILE"
set +a

# Extract Supabase project reference from URL
if [ -n "$SUPABASE_URL" ]; then
    SUPABASE_PROJECT_REF=$(echo "$SUPABASE_URL" | sed -n 's|https://\([^.]*\)\.supabase\.co|\1|p')
    if [ -z "$SUPABASE_PROJECT_REF" ]; then
        echo -e "${RED}Error: Could not extract project reference from SUPABASE_URL${NC}"
        exit 1
    fi
    echo "Supabase Project Reference: $SUPABASE_PROJECT_REF"
else
    echo -e "${RED}Error: SUPABASE_URL not set in $ENV_FILE${NC}"
    exit 1
fi

# Validate required Supabase variables
REQUIRED_VARS=("SUPABASE_URL" "SUPABASE_SERVICE_ROLE_KEY" "DATABASE_URL" "POSTGRES_PASSWORD")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}Error: Required variable $var is not set in $ENV_FILE${NC}"
        exit 1
    fi
done
echo "All required Supabase environment variables are set."

echo -e "${GREEN}Step 3: Creating shared Docker network...${NC}"
docker network create ml_network || true

echo -e "${GREEN}Step 4: Running Supabase database migrations...${NC}"
npx supabase db push --db-url "$DATABASE_URL" --password "$POSTGRES_PASSWORD" || {
    echo -e "${RED}Error: Database migration failed!${NC}"
    exit 1
}
echo -e "${GREEN}Database migrations completed successfully.${NC}"

echo -e "${GREEN}Step 5: Deploying Supabase edge functions...${NC}"

# Link to Supabase project
echo "Linking to Supabase project: $SUPABASE_PROJECT_REF"
npx supabase link --project-ref "$SUPABASE_PROJECT_REF" || {
    echo -e "${RED}Error: Failed to link to Supabase project!${NC}"
    echo "You may need to run 'npx supabase login' manually first."
    exit 1
}

# Deploy all functions
FUNCTIONS_DIR="supabase/functions"
DEPLOYED_FUNCTIONS=()
FAILED_FUNCTIONS=()

if [ ! -d "$FUNCTIONS_DIR" ]; then
    echo -e "${RED}Error: Functions directory not found: $FUNCTIONS_DIR${NC}"
    exit 1
fi

echo "Discovering functions in $FUNCTIONS_DIR..."
for func_dir in "$FUNCTIONS_DIR"/*/ ; do
    if [ -d "$func_dir" ]; then
        func_name=$(basename "$func_dir")

        # Skip special directories (starting with _ or .)
        if [[ "$func_name" == _* ]] || [[ "$func_name" == .* ]]; then
            echo "Skipping special directory: $func_name"
            continue
        fi

        echo "Deploying function: $func_name..."
        if npx supabase functions deploy "$func_name"; then
            echo -e "${GREEN}✓ Successfully deployed: $func_name${NC}"
            DEPLOYED_FUNCTIONS+=("$func_name")
        else
            echo -e "${RED}✗ Failed to deploy: $func_name${NC}"
            FAILED_FUNCTIONS+=("$func_name")
        fi
    fi
done

# Report deployment summary
echo ""
echo "Deployment Summary:"
echo "  Successfully deployed: ${#DEPLOYED_FUNCTIONS[@]} function(s)"
for func in "${DEPLOYED_FUNCTIONS[@]}"; do
    echo "    - $func"
done

if [ ${#FAILED_FUNCTIONS[@]} -gt 0 ]; then
    echo "  Failed to deploy: ${#FAILED_FUNCTIONS[@]} function(s)"
    for func in "${FAILED_FUNCTIONS[@]}"; do
        echo "    - $func"
    done
    echo -e "${RED}Error: Some functions failed to deploy!${NC}"
    exit 1
fi

# Set function secrets
echo ""
echo "Setting edge function secrets..."
npx supabase secrets set \
    STRIPE_WEBHOOK_SECRET="$STRIPE_WEBHOOK_SECRET" \
    STRIPE_PRICE_ID_PRO="$STRIPE_PRICE_ID_PRO" \
    STRIPE_SECRET_KEY="$STRIPE_SECRET_KEY" \
    SUPABASE_URL="$SUPABASE_URL" \
    SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
    MLSERVICE_HOST="$MLSERVICE_HOST" \
    MLSERVICE_AUTH_KEY="$MLSERVICE_AUTH_KEY" \
    MY_JWT_SECRET="$MY_JWT_SECRET" || {
    echo -e "${RED}Error: Failed to set function secrets!${NC}"
    exit 1
}
echo -e "${GREEN}All edge functions deployed and configured successfully.${NC}"

echo -e "${GREEN}Step 6: Building Docker images for Main Host...${NC}"
docker compose -f "$COMPOSE_FILE" build $BUILD_CACHE_FLAG ml-api parser datalab-parser fast-parser celery-beat

echo -e "${GREEN}Step 7: Deploying to Main Host...${NC}"
docker compose -f "$COMPOSE_FILE" down
echo "Starting RabbitMQ..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate rabbitmq

# Wait for RabbitMQ to be healthy
MAX_WAIT=120
WAITED=0
echo "Waiting for RabbitMQ to become healthy..."
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' rabbitmq-prod 2>/dev/null || echo "no-healthcheck")

    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}RabbitMQ is healthy!${NC}"
        break
    fi

    echo "RabbitMQ status: $HEALTH_STATUS ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

FINAL_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' rabbitmq-prod 2>/dev/null || echo "no-healthcheck")
if [ "$FINAL_HEALTH" != "healthy" ]; then
    echo -e "${RED}Error: RabbitMQ is not healthy (status: $FINAL_HEALTH)${NC}"
    echo "Checking logs..."
    docker compose -f "$COMPOSE_FILE" logs rabbitmq
    exit 1
fi

echo "Starting ML API, Parser, Datalab Parser, Fast Parser, Celery Beat, and Cloudflare Tunnel..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate ml-api parser datalab-parser fast-parser celery-beat cloudflared

# Wait for ML API to be healthy
WAITED=0
echo "Waiting for ML API to become healthy..."
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' ml-api-prod 2>/dev/null || echo "no-healthcheck")

    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}ML API is healthy!${NC}"
        break
    fi

    echo "ML API status: $HEALTH_STATUS ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

FINAL_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' ml-api-prod 2>/dev/null || echo "no-healthcheck")
if [ "$FINAL_HEALTH" != "healthy" ]; then
    echo -e "${RED}Error: ML API is not healthy (status: $FINAL_HEALTH)${NC}"
    echo "Checking logs..."
    docker compose -f "$COMPOSE_FILE" logs ml-api
    exit 1
fi

# Wait for Parser to be healthy
WAITED=0
echo "Waiting for Parser to become healthy..."
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH_STATUS=$(docker inspect --format='{{.State.Health.Status}}' parser-prod 2>/dev/null || echo "no-healthcheck")

    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}Parser is healthy!${NC}"
        break
    fi

    echo "Parser status: $HEALTH_STATUS ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

FINAL_HEALTH=$(docker inspect --format='{{.State.Health.Status}}' parser-prod 2>/dev/null || echo "no-healthcheck")
if [ "$FINAL_HEALTH" != "healthy" ]; then
    echo -e "${RED}Error: Parser is not healthy (status: $FINAL_HEALTH)${NC}"
    echo "Checking logs..."
    docker compose -f "$COMPOSE_FILE" logs parser
    exit 1
fi

echo "Starting monitoring services (Prometheus, Grafana, Flower, node_exporter, gpu_exporter)..."
docker compose -f "$COMPOSE_FILE" up -d --force-recreate prometheus grafana node_exporter gpu_exporter flower
echo -e "${GREEN}Monitoring services started.${NC}"

echo -e "${GREEN}Step 8: Deploying to Remote Host...${NC}"
echo "Creating directories on remote host..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "mkdir -p ${REMOTE_DIR}/ml-service ${REMOTE_DIR}/hf-cache ${REMOTE_DIR}/dl-cache"

echo "Syncing files to remote host..."
rsync -avz --progress \
    ./ml-service/ \
    ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/ml-service/ \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.git'

rsync -avz ${ENV_FILE} ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/

# Create temporary remote compose file with updated tun0 IP
echo "Templating docker-compose.remote.yml with detected tun0 IP: ${MAIN_HOST_TUN0}"
TEMP_REMOTE_COMPOSE=$(mktemp)
sed "s/__MAIN_HOST_TUN0__/${MAIN_HOST_TUN0}/" ${REMOTE_COMPOSE_FILE} > ${TEMP_REMOTE_COMPOSE}
rsync -avz ${TEMP_REMOTE_COMPOSE} ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/${REMOTE_COMPOSE_FILE}
rm ${TEMP_REMOTE_COMPOSE}

echo "Building and starting converter on remote host..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && TTS_DOCKERFILE=${TTS_DOCKERFILE} TTS_ENGINE=${TTS_ENGINE} docker compose -f ${REMOTE_COMPOSE_FILE} build $BUILD_CACHE_FLAG"
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && TTS_DOCKERFILE=${TTS_DOCKERFILE} TTS_ENGINE=${TTS_ENGINE} docker compose -f ${REMOTE_COMPOSE_FILE} down"
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && TTS_DOCKERFILE=${TTS_DOCKERFILE} TTS_ENGINE=${TTS_ENGINE} docker compose -f ${REMOTE_COMPOSE_FILE} up -d --force-recreate"

# Wait for Converter to be healthy
WAITED=0
echo "Waiting for Converter to become healthy..."
while [ $WAITED -lt $MAX_WAIT ]; do
    HEALTH_STATUS=$(ssh ${REMOTE_USER}@${REMOTE_HOST} "docker inspect --format='{{.State.Health.Status}}' converter-prod 2>/dev/null" || echo "no-healthcheck")

    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}Converter is healthy!${NC}"
        break
    fi

    echo "Converter status: $HEALTH_STATUS ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

FINAL_HEALTH=$(ssh ${REMOTE_USER}@${REMOTE_HOST} "docker inspect --format='{{.State.Health.Status}}' converter-prod 2>/dev/null" || echo "no-healthcheck")
if [ "$FINAL_HEALTH" != "healthy" ]; then
    echo -e "${RED}Error: Converter is not healthy (status: $FINAL_HEALTH)${NC}"
    echo "Checking logs..."
    ssh ${REMOTE_USER}@${REMOTE_HOST} "docker logs converter-prod"
    exit 1
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Services running:"
echo "  Main Host:"
echo "    - ml-api-prod           (port 8001)"
echo "    - parser-prod           (GPU 0, parse_queue)"
echo "    - datalab-parser-prod   (CPU, datalab_parse_queue, 5 workers)"
echo "    - fast-parser-prod      (CPU, fast_parse_queue, 5 workers)"
echo "    - celery-beat-prod      (backend_cleanup scheduler)"
echo "    - cloudflared-prod      (tunnel to ml-tunnel.textbook-tts.com)"
echo "    - rabbitmq-prod     (port 5672 on ${MAIN_HOST_TUN0})"
echo "    - prometheus-prod   (localhost:9090)"
echo "    - grafana-prod      (localhost:3000)"
echo "    - node_exporter     (internal)"
echo "    - gpu_exporter      (internal)"
echo "    - flower-prod       (localhost:5555)"
echo ""
echo "  Remote Host (${REMOTE_HOST}):"
echo "    - converter-prod    (GPU, convert_queue)"
echo ""
echo "  Dashboard access (SSH tunnel):"
echo "    ssh -L 3000:localhost:3000 -L 5555:localhost:5555 -L 9090:localhost:9090 <server>"
echo ""
echo "Main host services status:"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "To view logs:"
echo "  Main Host:"
echo "    docker compose -f $COMPOSE_FILE logs -f ml-api"
echo "    docker compose -f $COMPOSE_FILE logs -f parser"
echo "    docker compose -f $COMPOSE_FILE logs -f datalab-parser"
echo "    docker compose -f $COMPOSE_FILE logs -f fast-parser"
echo "    docker compose -f $COMPOSE_FILE logs -f celery-beat"
echo "    docker compose -f $COMPOSE_FILE logs -f rabbitmq"
echo "    docker compose -f $COMPOSE_FILE logs -f grafana"
echo ""
echo "  Remote Host:"
echo "    ssh ${REMOTE_USER}@${REMOTE_HOST} 'docker logs -f converter-prod'"
echo ""
echo "To stop services:"
echo "  Main Host:"
echo "    docker compose -f $COMPOSE_FILE down"
echo "  Remote Host:"
echo "    ssh ${REMOTE_USER}@${REMOTE_HOST} 'cd ${REMOTE_DIR} && docker compose -f ${REMOTE_COMPOSE_FILE} down'"
echo ""
