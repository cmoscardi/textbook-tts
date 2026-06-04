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
#   ./autoscaler/snapshot_bake.sh
#

# we are in autoscaler/
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# cd to project root
cd $SCRIPT_DIR/..


RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

REGION="${DO_REGION:-nyc3}"
# IMPORTANT: a snapshot can only be restored onto a droplet whose disk is >= this size's
# disk. s-2vcpu-4gb has an 80GB disk, so every droplet_size in autoscaler/config.py must
# also have >= 80GB disk. If you shrink this to bake cheaper, shrink the launch sizes to
# match, or DO returns 422 "Cannot create a droplet with a smaller disk than the image".
SIZE="s-2vcpu-4gb"  # 80GB disk; large enough to build the worker images
BASE_IMAGE="ubuntu-24-04-x64"
DROPLET_NAME="snapshot-bake-$(date +%s)"
SNAPSHOT_NAME="autoscaler-workers-$(date +%Y%m%d-%H%M%S)"

source .env.production

if [ -z "$DIGITALOCEAN_API_TOKEN" ]; then
    echo -e "${RED}Error: DIGITALOCEAN_API_TOKEN not set${NC}"
    exit 1
fi

# doctl authenticates via its own stored config or DIGITALOCEAN_ACCESS_TOKEN — it does NOT
# read DIGITALOCEAN_API_TOKEN. Point it at the same token .env.production carries so a rotated
# token (e.g. after adding a scope) doesn't leave doctl using a stale stored token (401).
export DIGITALOCEAN_ACCESS_TOKEN="$DIGITALOCEAN_API_TOKEN"

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
ssh root@"$DROPLET_IP" "mkdir -p /opt/autoscaler"
rsync -az "$SCRIPT_DIR/start-worker.sh" root@"$DROPLET_IP":/opt/autoscaler/start-worker.sh
ssh root@"$DROPLET_IP" "chmod +x /opt/autoscaler/start-worker.sh"

echo -e "${GREEN}Step 6: Creating snapshot...${NC}"
# Power off before snapshot for consistency
doctl compute droplet-action power-off "$DROPLET_ID" --wait

doctl compute droplet-action snapshot "$DROPLET_ID" \
    --snapshot-name "$SNAPSHOT_NAME" \
    --wait \
    --no-header >/dev/null

# Resolve the real snapshot RESOURCE id by its (unique, timestamped) name.
# (Do NOT use the droplet's SnapshotIDs field — doctl renders an empty slice as the literal
# string "<nil>", which silently poisons everything downstream.)
NEW_SNAPSHOT_ID=$(doctl compute snapshot list --format ID,Name --no-header \
    | awk -v n="$SNAPSHOT_NAME" '$2==n {print $1}' | head -1)

# Validate: must be a non-empty, purely-numeric ID. Empty or "<nil>" is a hard failure —
# bail out BEFORE pruning (a bad id would make the prune delete every snapshot) and BEFORE
# writing the artifact file (a bad id would corrupt .env.production downstream).
if ! printf '%s' "$NEW_SNAPSHOT_ID" | grep -qE '^[0-9]+$'; then
    echo -e "${RED}Error: could not resolve a valid numeric snapshot ID for $SNAPSHOT_NAME (got: '${NEW_SNAPSHOT_ID:-<empty>}')${NC}"
    doctl compute droplet delete "$DROPLET_ID" --force || true
    exit 1
fi
echo "Resolved snapshot ID: $NEW_SNAPSHOT_ID"

echo -e "${GREEN}Step 7: Cleaning up temporary droplet...${NC}"
doctl compute droplet delete "$DROPLET_ID" --force

# Emit the ID for deploy.sh to wire into .env.production (artifact file, not the secrets file).
echo "$NEW_SNAPSHOT_ID" > "$SCRIPT_DIR/../.last-snapshot-id"

# Prune older autoscaler-workers-* snapshots to avoid storage-cost creep (keep the new one).
# Safe now that NEW_SNAPSHOT_ID is a validated numeric id. Best-effort: a delete hiccup must
# not fail the bake (the new snapshot is already created).
echo -e "${GREEN}Step 8: Pruning old worker snapshots...${NC}"
doctl compute snapshot list --format ID,Name --no-header \
    | awk '$2 ~ /^autoscaler-workers-/ {print $1}' \
    | grep -vx "$NEW_SNAPSHOT_ID" \
    | xargs -r -I{} sh -c 'echo "Deleting old snapshot {}"; doctl compute snapshot delete {} --force || true' \
    || true

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Snapshot baked successfully!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Snapshot name: $SNAPSHOT_NAME"
echo "Snapshot ID:   $NEW_SNAPSHOT_ID  (written to .last-snapshot-id)"
echo ""
echo "When invoked by deploy/deploy.sh this ID is wired into .env.production automatically."
echo "If you ran this script standalone, set these three vars in .env.production:"
echo "  DO_FAST_PARSER_SNAPSHOT_ID=$NEW_SNAPSHOT_ID"
echo "  DO_DATALAB_PARSER_SNAPSHOT_ID=$NEW_SNAPSHOT_ID"
echo "  DO_CONVERTER_SNAPSHOT_ID=$NEW_SNAPSHOT_ID"
echo ""
echo "(All three use the same snapshot — the WORKER_TYPE env var selects the image at boot)"
