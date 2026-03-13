#!/usr/bin/env bash
set -euo pipefail

# Build and run the load test in Docker.
# All arguments are forwarded to loadtest.py.
#
# Usage:
#   ./loadtest/run.sh run --rate 0.1 --users 2 --max-sentences 5
#   ./loadtest/run.sh cleanup --dry-run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."

# Source production env if available (for SUPABASE_URL, keys, etc.)
ENV_FILE="$REPO_ROOT/.env.production"
ENV_ARGS=()
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
fi

# Map env vars to --env flags for docker run
# captcha_secret is lowercase in .env.production, normalize it
CAPTCHA_SECRET="${CAPTCHA_SECRET:-${captcha_secret:-}}"

for var in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY SUPABASE_ACCESS_TOKEN CAPTCHA_SECRET; do
  if [[ -n "${!var:-}" ]]; then
    ENV_ARGS+=(-e "$var=${!var}")
  fi
done

IMAGE_NAME="textbook-tts-loadtest"

# Build image (quiet if up to date)
docker build -q -t "$IMAGE_NAME" "$SCRIPT_DIR" >/dev/null

# Mount test-pdfs directory and run
docker run --rm -it \
  "${ENV_ARGS[@]}" \
  -v "$SCRIPT_DIR/test-pdfs:/loadtest/test-pdfs:ro" \
  -v "$REPO_ROOT/loadtest:/loadtest/output:rw" \
  "$IMAGE_NAME" \
  "$@"
