#!/bin/bash
set -e

# Production deployment script for ML Service and RabbitMQ
# Usage: ./deploy/deploy.sh

echo "========================================="
echo "ML Service Production Deployment"
echo "========================================="

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
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

echo -e "${GREEN}Step 5: Building Docker images...${NC}"
docker compose -f "$COMPOSE_FILE" build

echo -e "${GREEN}Step 6: Stopping existing containers...${NC}"
docker compose -f "$COMPOSE_FILE" down || true

echo -e "${GREEN}Step 7: Starting services...${NC}"
docker compose -f "$COMPOSE_FILE" up -d

echo -e "${GREEN}Step 8: Waiting for services to be healthy...${NC}"
sleep 10

# Wait for ML service to be healthy
MAX_WAIT=120
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if docker compose -f "$COMPOSE_FILE" ps | grep -q "ml-service-prod.*healthy"; then
        echo -e "${GREEN}ML Service is healthy!${NC}"
        break
    fi
    echo "Waiting for ML service to be healthy... ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}Error: ML service failed to become healthy within $MAX_WAIT seconds${NC}"
    echo "Checking logs..."
    docker compose -f "$COMPOSE_FILE" logs ml-service
    exit 1
fi

# Wait for RabbitMQ to be healthy
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if docker compose -f "$COMPOSE_FILE" ps | grep -q "rabbitmq-prod.*healthy"; then
        echo -e "${GREEN}RabbitMQ is healthy!${NC}"
        break
    fi
    echo "Waiting for RabbitMQ to be healthy... ($WAITED/$MAX_WAIT seconds)"
    sleep 5
    WAITED=$((WAITED + 5))
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo -e "${RED}Error: RabbitMQ failed to become healthy within $MAX_WAIT seconds${NC}"
    echo "Checking logs..."
    docker compose -f "$COMPOSE_FILE" logs rabbitmq
    exit 1
fi

echo -e "${GREEN}Step 9: Verifying deployment...${NC}"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Deployment completed successfully!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Services status:"
docker compose -f "$COMPOSE_FILE" ps

echo ""
echo "To view logs:"
echo "  docker compose -f $COMPOSE_FILE logs -f ml-service"
echo "  docker compose -f $COMPOSE_FILE logs -f rabbitmq"
echo ""
echo "To stop services:"
echo "  docker compose -f $COMPOSE_FILE down"
echo ""
