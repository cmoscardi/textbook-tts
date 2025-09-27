#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
docker network create ttsnet
cd $SCRIPT_DIR/supabase-env
docker compose -f docker-compose.yml -f docker-compose.s3.yml up -d
./custom-init.sh
cd $SCRIPT_DIR

# Check if nvidia runtime is available
if docker info 2>/dev/null | grep -q "nvidia"; then
    echo "NVIDIA runtime detected, using GPU acceleration..."
    export DOCKER_RUNTIME=nvidia
    export NVIDIA_VISIBLE_DEVICES=all
else
    echo "No NVIDIA runtime detected, using CPU-only mode..."
    export DOCKER_RUNTIME=runc
    export NVIDIA_VISIBLE_DEVICES=none
fi

docker compose up -d
