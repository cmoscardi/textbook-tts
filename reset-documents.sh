#!/bin/bash
# reset-documents.sh
# Deletes all document data (files, pages, sentences, parsings, conversions)
# and clears Supabase storage, while preserving user accounts and subscriptions.
#
# Usage: ./reset-documents.sh [--prod]
#   --prod    Use .env.production and production Supabase URL

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# Determine environment
if [ "${1:-}" = "--prod" ]; then
  ENV_FILE="$SCRIPT_DIR/.env.production"
  echo "*** PRODUCTION MODE ***"
else
  ENV_FILE="$SCRIPT_DIR/.env.development"
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: $ENV_FILE not found"
  exit 1
fi

# Extract a plain (unquoted) value from env file
get_env() {
  grep "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '"'
}

POSTGRES_PASSWORD=$(get_env POSTGRES_PASSWORD)

if [ "${1:-}" = "--prod" ]; then
  POSTGRES_HOST=$(get_env POSTGRES_HOST)
  POSTGRES_PORT=$(get_env POSTGRES_PORT)
  POSTGRES_USER=$(get_env POSTGRES_USER)
  PGCONN="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres"
  SUPABASE_URL=$(get_env SUPABASE_URL)
  SUPABASE_SERVICE_KEY=$(get_env SUPABASE_SERVICE_ROLE_KEY)
else
  PGCONN="postgresql://postgres:${POSTGRES_PASSWORD}@localhost:54322/postgres"
  SUPABASE_URL="http://localhost:54321"
  SUPABASE_SERVICE_KEY=$(get_env SUPABASE_SERVICE_ROLE_KEY)
fi

# --- Safety confirmation ---
echo ""
echo "This will DELETE:"
echo "  - All files, file_parsings, file_conversions, file_pages, page_sentences"
echo "  - All objects in Supabase storage bucket 'files'"
echo ""
echo "This will PRESERVE:"
echo "  - User accounts (auth.users)"
echo "  - User profiles & subscriptions (user_profiles)"
echo "  - Usage tracking (usage_tracking)"
echo "  - Stripe events (stripe_events)"
echo "  - Subscription config (subscription_config)"
echo ""
read -p "Are you sure? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# --- Database cleanup ---
# Deleting from 'files' cascades to file_parsings, file_conversions, file_pages, page_sentences
echo "==> Deleting all document data from database..."
DELETED=$(psql "$PGCONN" -t -A -c "DELETE FROM files RETURNING file_id" | wc -l | tr -d ' ')
echo "    Deleted $DELETED file(s) (cascaded to parsings, conversions, pages, sentences)"

# --- Storage cleanup ---
echo "==> Clearing Supabase storage bucket 'files'..."

# List all top-level folders (user UUIDs)
FOLDERS=$(curl -s -X POST \
  "${SUPABASE_URL}/storage/v1/object/list/files" \
  -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
  -H "apikey: ${SUPABASE_SERVICE_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"prefix":"","limit":10000}')

# Extract folder names (user ID prefixes)
PREFIXES=$(echo "$FOLDERS" | python3 -c "
import sys, json
items = json.load(sys.stdin)
for item in items:
    name = item.get('name', '')
    if name:
        print(name)
" 2>/dev/null || true)

if [ -z "$PREFIXES" ]; then
  echo "    No objects found in storage."
else
  TOTAL_DELETED=0
  for prefix in $PREFIXES; do
    # List all objects under this prefix
    OBJECTS=$(curl -s -X POST \
      "${SUPABASE_URL}/storage/v1/object/list/files" \
      -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
      -H "apikey: ${SUPABASE_SERVICE_KEY}" \
      -H "Content-Type: application/json" \
      -d "{\"prefix\":\"${prefix}/\",\"limit\":10000}")

    # Build list of full paths
    PATHS=$(echo "$OBJECTS" | python3 -c "
import sys, json
items = json.load(sys.stdin)
paths = []
for item in items:
    name = item.get('name', '')
    if name:
        paths.append('${prefix}/' + name)
if paths:
    print(json.dumps(paths))
" 2>/dev/null || true)

    if [ -n "$PATHS" ] && [ "$PATHS" != "[]" ]; then
      COUNT=$(echo "$PATHS" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
      curl -s -X DELETE \
        "${SUPABASE_URL}/storage/v1/object/files" \
        -H "Authorization: Bearer ${SUPABASE_SERVICE_KEY}" \
        -H "apikey: ${SUPABASE_SERVICE_KEY}" \
        -H "Content-Type: application/json" \
        -d "{\"prefixes\": $PATHS}" > /dev/null
      TOTAL_DELETED=$((TOTAL_DELETED + COUNT))
      echo "    Deleted $COUNT object(s) under $prefix/"
    fi
  done
  echo "    Total: $TOTAL_DELETED storage object(s) deleted"
fi

echo ""
echo "Done. All document data cleared. User accounts and subscriptions preserved."
