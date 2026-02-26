#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd $SCRIPT_DIR
npx supabase start
#./custom-init.sh
cd $SCRIPT_DIR

# Check if nvidia runtime is available
if docker info 2>/dev/null | grep -q "nvidia"; then
    # echo "NVIDIA runtime detected, using GPU acceleration..."
    echo "CUDA detected, using gpu accel"
    export DOCKER_RUNTIME=nvidia
    export NVIDIA_VISIBLE_DEVICES=0
else
    echo "No NVIDIA runtime detected, using CPU-only mode..."
    export DOCKER_RUNTIME=runc
    export NVIDIA_VISIBLE_DEVICES=none
fi

sleep 5

docker compose up $1 -d
NETWORK_ID=$(docker network ls --filter name=supabase_network_textbook-tts --format "{{.ID}}")
npx supabase functions serve --env-file .env.development --network-id $NETWORK_ID &

# Wait for edge runtime container to be created
echo "Waiting for edge runtime container to start..."
sleep 3

# Connect edge runtime to the Supabase network so Kong can reach it
echo "Connecting edge runtime to Supabase network..."
docker network connect supabase_network_textbook-tts supabase_edge_runtime_textbook-tts 2>/dev/null || echo "Edge runtime already connected or not yet ready"

echo "Services started successfully!"
echo "Edge Functions available at: http://localhost:54321/functions/v1/"

echo "Starting Stripe listener..."
stripe listen --forward-to localhost:54321/functions/v1/stripe-webhook

# Keep script running (since supabase functions serve is in background)
wait
