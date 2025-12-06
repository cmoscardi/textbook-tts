#!/bin/bash
#

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
#docker network create ttsnet
npx supabase stop
#./custom-init.sh
cd $SCRIPT_DIR



docker compose down
