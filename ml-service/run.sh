#!/bin/bash
#

./install.sh

uvicorn api:app --reload --host 0.0.0.0 --port 8000
