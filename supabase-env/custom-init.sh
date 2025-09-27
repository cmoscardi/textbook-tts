#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Load environment variables
source .env

# extra 10 seconds to make sure we can run db push
sleep 10

$SCRIPT_DIR/../supabase-db-push.sh

# Execute the init.sql file in the database container
docker compose exec db psql -U postgres -d postgres -f /custom-init/file_upload_policy.sql
