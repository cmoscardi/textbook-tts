#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR
npx supabase start
#./custom-init.sh
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

sleep 5

docker compose up -d
