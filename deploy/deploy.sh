#!/bin/bash
set -e

# Production deployment script for ML Service and RabbitMQ
# Multi-host deployment: Main host + Remote GPU host
# Usage: ./deploy/deploy.sh

echo "========================================="
echo "ML Service Production Deployment"
echo "Multi-GPU Setup (Main + Remote Host)"
echo "========================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Multi-host configuration
REMOTE_USER="christian"
REMOTE_HOST="192.168.1.15"
REMOTE_DIR="~/textbook-tts"
MAIN_HOST_TUN0="10.8.0.10"

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

echo -e "${GREEN}Step 3: Running Supabase database migrations...${NC}"
npx supabase db push --db-url "$DATABASE_URL" --password "$POSTGRES_PASSWORD" || {
    echo -e "${RED}Error: Database migration failed!${NC}"
    exit 1
}
echo -e "${GREEN}Database migrations completed successfully.${NC}"

echo -e "${GREEN}Step 4: Deploying Supabase edge functions...${NC}"

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
    SUPABASE_URL="$SUPABASE_URL" \
    SUPABASE_SERVICE_ROLE_KEY="$SUPABASE_SERVICE_ROLE_KEY" \
    MLSERVICE_HOST="$MLSERVICE_HOST" \
    MLSERVICE_AUTH_KEY="$MLSERVICE_AUTH_KEY" || {
    echo -e "${RED}Error: Failed to set function secrets!${NC}"
    exit 1
}
echo -e "${GREEN}All edge functions deployed and configured successfully.${NC}"

echo -e "${GREEN}Step 5: Building Docker images for Main Host...${NC}"
docker compose -f "$COMPOSE_FILE" build ml-api parser

echo -e "${GREEN}Step 6: Deploying to Main Host...${NC}"
echo "Starting RabbitMQ..."
docker compose -f "$COMPOSE_FILE" up -d rabbitmq

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

echo "Starting ML API and Parser..."
docker compose -f "$COMPOSE_FILE" up -d ml-api parser

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

echo -e "${GREEN}Step 7: Deploying to Remote Host...${NC}"
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
rsync -avz ${REMOTE_COMPOSE_FILE} ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/

echo "Building and starting converter on remote host..."
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && docker compose -f ${REMOTE_COMPOSE_FILE} build"
ssh ${REMOTE_USER}@${REMOTE_HOST} "cd ${REMOTE_DIR} && docker compose -f ${REMOTE_COMPOSE_FILE} up -d"

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
echo "    - ml-api-prod     (port 8001)"
echo "    - parser-prod     (GPU 0, parse_queue)"
echo "    - rabbitmq-prod   (port 5672 on ${MAIN_HOST_TUN0})"
echo ""
echo "  Remote Host (${REMOTE_HOST}):"
echo "    - converter-prod  (GPU, convert_queue)"
echo ""
echo "Main host services status:"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "To view logs:"
echo "  Main Host:"
echo "    docker compose -f $COMPOSE_FILE logs -f ml-api"
echo "    docker compose -f $COMPOSE_FILE logs -f parser"
echo "    docker compose -f $COMPOSE_FILE logs -f rabbitmq"
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
