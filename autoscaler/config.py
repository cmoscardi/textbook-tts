"""Autoscaler configuration — scaling thresholds, DO settings, queue definitions."""

import os

# DigitalOcean settings
DO_API_TOKEN = os.environ.get("DIGITALOCEAN_API_TOKEN", "")
DO_REGION = os.environ.get("DO_REGION", "nyc3")
DO_SSH_KEY_FINGERPRINT = os.environ.get("DO_SSH_KEY_FINGERPRINT", "")

# RabbitMQ management API (localhost only, same host as autoscaler)
RABBITMQ_MGMT_URL = os.environ.get("RABBITMQ_MGMT_URL", "http://rabbitmq-prod:15672")
RABBITMQ_MGMT_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_MGMT_PASS = os.environ.get("RABBITMQ_PASS", "guest")

# Main host public IP (for droplets to connect to RabbitMQ)
MAIN_HOST_IP = os.environ.get("MAIN_HOST_IP", "")

# Env vars passed to droplets via cloud-init
RABBITMQ_USER = os.environ.get("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.environ.get("RABBITMQ_PASS", "guest")
DATABASE_CELERY_URL = os.environ.get("DATABASE_CELERY_URL", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DATALAB_API_KEY = os.environ.get("DATALAB_API_KEY", "")
TTS_ENGINE = os.environ.get("TTS_ENGINE", "supertonic")

# Worker scaling definitions.
#
# Keyed by worker_type. Each worker serves one or more queues (the converter
# serves both convert_queue and synthesize_queue — see run-converter.prod.sh).
# A worker group's scaling decision is driven by the COMBINED depth across all
# its queues; the per-queue `task_duration_avg_s` weights drain-time estimation.
SCALABLE_WORKERS = {
    "fast-parser": {
        "queues": {
            "fast_parse_queue": {"task_duration_avg_s": 1},  # ~0.5s parse + overhead
        },
        "snapshot_id": os.environ.get("DO_FAST_PARSER_SNAPSHOT_ID", ""),
        # NOTE: must have disk >= the snapshot's source disk (snapshot_bake.sh bakes on
        # s-2vcpu-4gb = 80GB), or DO returns 422 "smaller disk than the image".
        "droplet_size": "s-2vcpu-4gb",      # $24/mo = $0.036/hr (80GB disk, matches snapshot)
        "hourly_cost": 0.036,
        "local_concurrency": 5,
        "remote_concurrency": 5,
        "scale_up_threshold": 20,            # combined ready messages to trigger
        "scale_down_idle_s": 300,            # 5 min idle -> destroy
        "max_droplets": 3,
        "cooldown_s": 180,                   # 3 min between scale events
    },
    "datalab-parser": {
        "queues": {
            "datalab_parse_queue": {"task_duration_avg_s": 5},
        },
        "snapshot_id": os.environ.get("DO_DATALAB_PARSER_SNAPSHOT_ID", ""),
        "droplet_size": "s-2vcpu-4gb",      # 80GB disk to match the shared snapshot (see fast-parser note)
        "hourly_cost": 0.036,
        "local_concurrency": 5,
        "remote_concurrency": 5,
        "scale_up_threshold": 10,
        "scale_down_idle_s": 300,
        "max_droplets": 3,
        "cooldown_s": 180,
    },
    "converter": {
        "queues": {
            "convert_queue": {"task_duration_avg_s": 60},     # whole-file synth, slow
            "synthesize_queue": {"task_duration_avg_s": 3},   # per-sentence, fast/high-volume
        },
        "snapshot_id": os.environ.get("DO_CONVERTER_SNAPSHOT_ID", ""),
        # Cheapest 8-vCPU box (320GB disk >> 80GB shared-snapshot floor). 8 solo TTS workers.
        "droplet_size": "s-8vcpu-16gb",      # $96/mo = $0.143/hr
        "hourly_cost": 0.143,
        "local_concurrency": 10,             # 10 solo workers locally
        "remote_concurrency": 8,             # 8 solo workers per droplet (drives CONVERTER_WORKERS)
        "scale_up_threshold": 2,            # higher threshold (more local capacity)
        "scale_down_idle_s": 300,
        "max_droplets": 3,
        "cooldown_s": 180,
    },
}

# Global limits
POLL_INTERVAL_S = 30
GLOBAL_MAX_DROPLETS = 8
MONTHLY_COST_CAP_USD = float(os.environ.get("AUTOSCALER_MONTHLY_COST_CAP", "50"))
STATE_FILE = os.environ.get("AUTOSCALER_STATE_FILE", "/var/lib/autoscaler/state.json")

# Alert thresholds
WARN_COST_RATIO = 0.8  # warn at 80% of monthly cap

# Tag used to identify autoscaler-managed droplets
MANAGED_TAG = "autoscaler-managed"
