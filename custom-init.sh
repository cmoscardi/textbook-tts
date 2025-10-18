#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

# Load environment variables
source .env.development

# extra 10 seconds to make sure we can run db push
sleep 10

#$SCRIPT_DIR/supabase-db-push.sh
npx supabase start


cat $SCRIPT_DIR/supabase/schemas/file_upload_policy.sql | docker exec -i supabase_db_textbook-tts psql -U postgres -d postgres

