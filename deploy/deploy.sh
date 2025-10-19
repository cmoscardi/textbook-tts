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

echo -e "${GREEN}Step 2: Building Docker images...${NC}"
docker compose -f "$COMPOSE_FILE" build --no-cache

echo -e "${GREEN}Step 3: Stopping existing containers...${NC}"
docker compose -f "$COMPOSE_FILE" down || true

echo -e "${GREEN}Step 4: Starting services...${NC}"
docker compose -f "$COMPOSE_FILE" up -d

echo -e "${GREEN}Step 5: Waiting for services to be healthy...${NC}"
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

echo -e "${GREEN}Step 6: Verifying deployment...${NC}"
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
