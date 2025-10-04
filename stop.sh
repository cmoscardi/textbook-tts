#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
#docker network create ttsnet
cd $SCRIPT_DIR/supabase-env
docker compose -f docker-compose.yml -f docker-compose.s3.yml down
#./custom-init.sh
cd $SCRIPT_DIR



docker compose down
