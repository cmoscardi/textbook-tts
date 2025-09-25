#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
docker network create ttsnet
cd $SCRIPT_DIR/supabase-env
docker compose up -d
cd $SCRIPT_DIR
docker compose up -d
