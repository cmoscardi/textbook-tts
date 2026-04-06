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

# Queue scaling definitions
SCALABLE_QUEUES = {
    "fast_parse_queue": {
        "worker_type": "fast-parser",
        "snapshot_id": os.environ.get("DO_FAST_PARSER_SNAPSHOT_ID", ""),
        "droplet_size": "s-1vcpu-1gb",      # $6/mo = $0.009/hr
        "hourly_cost": 0.009,
        "local_concurrency": 5,
        "remote_concurrency": 5,
        "task_duration_avg_s": 1,            # ~0.5s parse + overhead
        "scale_up_threshold": 20,            # queue depth to trigger
        "scale_down_idle_s": 300,            # 5 min idle -> destroy
        "max_droplets": 3,
        "cooldown_s": 180,                   # 3 min between scale events
    },
    "datalab_parse_queue": {
        "worker_type": "datalab-parser",
        "snapshot_id": os.environ.get("DO_DATALAB_PARSER_SNAPSHOT_ID", ""),
        "droplet_size": "s-1vcpu-1gb",
        "hourly_cost": 0.009,
        "local_concurrency": 5,
        "remote_concurrency": 5,
        "task_duration_avg_s": 20,
        "scale_up_threshold": 10,
        "scale_down_idle_s": 300,
        "max_droplets": 3,
        "cooldown_s": 180,
    },
    "convert_queue": {
        "worker_type": "converter",
        "snapshot_id": os.environ.get("DO_CONVERTER_SNAPSHOT_ID", ""),
        "droplet_size": "s-2vcpu-2gb",       # $12/mo — TTS needs more RAM
        "hourly_cost": 0.018,
        "local_concurrency": 10,             # 10 solo workers locally
        "remote_concurrency": 5,             # fewer on smaller droplet
        "task_duration_avg_s": 3,            # ~8s per sentence TTS
        "scale_up_threshold": 30,            # higher threshold (more local capacity)
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
