#!/usr/bin/env bash
# Downloads pre-built Grafana dashboards from grafana.com and patches them
# for use with file-based provisioning (replaces datasource template variables
# with the known UID "prometheus" set in datasources/prometheus.yml).
#
# Run once to populate monitoring/grafana/dashboards/:
#   bash monitoring/download-dashboards.sh

set -euo pipefail

DASHBOARDS_DIR="$(dirname "$0")/grafana/dashboards"

download_dashboard() {
  local id=$1
  local filename=$2
  local out="${DASHBOARDS_DIR}/${filename}.json"
  echo "Downloading dashboard ${filename} (grafana.com ID: ${id})..."
  curl -sf "https://grafana.com/api/dashboards/${id}/revisions/latest/download" \
    | sed 's/\${DS_PROMETHEUS}/prometheus/g' \
    | jq 'del(.__inputs, .__requires, .__elements)' \
    > "$out"
  echo "  -> $out"
}

download_dashboard 1860  "node_exporter_full"
download_dashboard 10991 "rabbitmq_overview"
download_dashboard 12239 "nvidia_gpu"

echo "Done. Restart Grafana to pick up changes (or it will reload within 30s)."
