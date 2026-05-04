#!/usr/bin/env python3
"""Celery worker autoscaler daemon.

Polls RabbitMQ queue depths and creates/destroys DigitalOcean droplets
to scale CPU workers (fast-parser, datalab-parser, converter) on demand.

Run as a systemd service or directly: python3 autoscaler.py
"""

import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
import do_client
import rabbitmq_client
import alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("autoscaler")

# Optional: expose Prometheus metrics
try:
    from prometheus_client import Gauge, Counter, start_http_server

    active_droplets_gauge = Gauge(
        "autoscaler_active_droplets", "Active autoscaler droplets", ["worker_type"]
    )
    scale_events_counter = Counter(
        "autoscaler_scale_events_total", "Scale events", ["action", "worker_type"]
    )
    monthly_cost_gauge = Gauge("autoscaler_monthly_cost_usd", "Monthly droplet cost")
    queue_depth_gauge = Gauge("autoscaler_queue_depth", "Queue depth", ["queue"])
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse_iso(s):
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_state():
    """Load autoscaler state from disk, or return empty state."""
    path = Path(config.STATE_FILE)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not load state file, starting fresh: {e}")

    return {
        "droplets": {},
        "last_scale_up": {},
        "monthly_hours": 0.0,
        "month": _now().strftime("%Y-%m"),
    }


def _save_state(state):
    """Persist state to disk."""
    path = Path(config.STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


def _reset_monthly_if_needed(state):
    """Reset monthly cost tracking at the start of a new month."""
    current_month = _now().strftime("%Y-%m")
    if state.get("month") != current_month:
        logger.info(f"New month ({current_month}), resetting monthly hours")
        state["monthly_hours"] = 0.0
        state["month"] = current_month


def _estimate_monthly_cost(state):
    """Estimate current month's droplet cost from tracked hours."""
    # Sum hourly costs of currently active droplets since last check
    total = 0.0
    for droplet_id, info in state.get("droplets", {}).items():
        queue = info.get("queue", "")
        q_config = config.SCALABLE_QUEUES.get(queue, {})
        hourly = q_config.get("hourly_cost", 0.01)
        created = _parse_iso(info["created_at"])
        hours_alive = (_now() - created).total_seconds() / 3600
        total += hours_alive * hourly

    return state.get("monthly_hours", 0.0) + total


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def _reconcile(state):
    """Sync local state with actual DO droplets.

    Handles: autoscaler crash/restart, orphaned droplets, manually deleted droplets.
    """
    actual = do_client.list_managed_droplets()
    actual_ids = {str(d.id) for d in actual}
    state_ids = set(state.get("droplets", {}).keys())

    # Remove droplets from state that no longer exist on DO
    gone = state_ids - actual_ids
    for did in gone:
        name = state["droplets"][did].get("name", did)
        logger.warning(f"Reconcile: droplet {name} ({did}) gone from DO, removing from state")
        # Credit the hours it was alive
        info = state["droplets"].pop(did)
        created = _parse_iso(info["created_at"])
        hours = (_now() - created).total_seconds() / 3600
        q_config = config.SCALABLE_QUEUES.get(info.get("queue", ""), {})
        state["monthly_hours"] += hours * q_config.get("hourly_cost", 0.01)

    # Adopt droplets on DO that aren't in our state (e.g. created before crash)
    for d in actual:
        if str(d.id) not in state.get("droplets", {}):
            # Try to figure out the queue from tags
            queue = ""
            worker_type = ""
            for tag in d.tags:
                if tag.startswith("queue:"):
                    queue = tag.split(":", 1)[1]
                if tag.startswith("worker-type:"):
                    worker_type = tag.split(":", 1)[1]
            logger.warning(f"Reconcile: adopting orphaned droplet {d.name} ({d.id})")
            state.setdefault("droplets", {})[str(d.id)] = {
                "name": d.name,
                "worker_type": worker_type,
                "queue": queue,
                "created_at": _iso(_now()),  # approximate
            }


# ---------------------------------------------------------------------------
# Cloud-init generation
# ---------------------------------------------------------------------------

def _make_user_data(worker_type):
    """Generate cloud-init user data for a droplet."""
    return f"""#!/bin/bash
# Written by autoscaler cloud-init
cat >> /etc/environment <<'ENVEOF'
RABBITMQ_HOST={config.MAIN_HOST_IP}
RABBITMQ_USER={config.RABBITMQ_USER}
RABBITMQ_PASS={config.RABBITMQ_PASS}
DATABASE_CELERY_URL={config.DATABASE_CELERY_URL}
SUPABASE_URL={config.SUPABASE_URL}
SUPABASE_SERVICE_ROLE_KEY={config.SUPABASE_SERVICE_ROLE_KEY}
DATALAB_API_KEY={config.DATALAB_API_KEY}
TTS_ENGINE={config.TTS_ENGINE}
CONVERTER_WORKERS=5
WORKER_TYPE={worker_type}
ENVEOF

# Source env and start the worker
set -a; source /etc/environment; set +a
/opt/autoscaler/start-worker.sh
"""


# ---------------------------------------------------------------------------
# Scaling decisions
# ---------------------------------------------------------------------------

def _count_droplets_for_queue(state, queue_name):
    return sum(
        1 for info in state.get("droplets", {}).values()
        if info.get("queue") == queue_name
    )


def _total_droplet_count(state):
    return len(state.get("droplets", {}))


def _cooldown_elapsed(state, queue_name, cooldown_s):
    last = state.get("last_scale_up", {}).get(queue_name)
    if not last:
        return True
    elapsed = (_now() - _parse_iso(last)).total_seconds()
    return elapsed >= cooldown_s


def evaluate_and_act(state, queue_depths):
    """Evaluate scaling decisions for all queues and act."""
    monthly_cost = _estimate_monthly_cost(state)

    if _HAS_PROMETHEUS:
        monthly_cost_gauge.set(monthly_cost)
        for q, depth in queue_depths.items():
            queue_depth_gauge.labels(queue=q).set(depth)

    # Cost cap check
    if monthly_cost >= config.MONTHLY_COST_CAP_USD:
        if monthly_cost >= config.MONTHLY_COST_CAP_USD * config.WARN_COST_RATIO:
            alerts.alert_cost_warning(monthly_cost, config.MONTHLY_COST_CAP_USD)
        logger.warning(f"Monthly cost ${monthly_cost:.2f} >= cap ${config.MONTHLY_COST_CAP_USD}, no scale-ups")

    for queue_name, q_config in config.SCALABLE_QUEUES.items():
        depth = queue_depths.get(queue_name, 0)
        num_droplets = _count_droplets_for_queue(state, queue_name)
        worker_type = q_config["worker_type"]

        if _HAS_PROMETHEUS:
            active_droplets_gauge.labels(worker_type=worker_type).set(num_droplets)

        # --- Scale UP ---
        total_concurrency = (
            q_config["local_concurrency"]
            + num_droplets * q_config["remote_concurrency"]
        )
        time_to_drain = (
            depth * q_config["task_duration_avg_s"] / max(total_concurrency, 1)
        )

        if (
            depth > q_config["scale_up_threshold"]
            and time_to_drain > 5
            and num_droplets < q_config["max_droplets"]
            and _total_droplet_count(state) < config.GLOBAL_MAX_DROPLETS
            and _cooldown_elapsed(state, queue_name, q_config["cooldown_s"])
            and monthly_cost < config.MONTHLY_COST_CAP_USD
            and q_config["snapshot_id"]
        ):
            try:
                droplet = do_client.create_droplet(
                    worker_type=worker_type,
                    queue_name=queue_name,
                    snapshot_id=q_config["snapshot_id"],
                    size=q_config["droplet_size"],
                    user_data=_make_user_data(worker_type),
                )
                state.setdefault("droplets", {})[str(droplet.id)] = {
                    "name": droplet.name,
                    "worker_type": worker_type,
                    "queue": queue_name,
                    "created_at": _iso(_now()),
                }
                state.setdefault("last_scale_up", {})[queue_name] = _iso(_now())
                _save_state(state)

                logger.info(f"SCALE UP: created {droplet.name} for {queue_name} (depth={depth})")
                alerts.alert_scale_up(droplet.name, queue_name, depth)

                if _HAS_PROMETHEUS:
                    scale_events_counter.labels(action="up", worker_type=worker_type).inc()

            except Exception as e:
                logger.error(f"Failed to scale up {worker_type}: {e}")
                alerts.alert_error(f"Failed to create {worker_type} droplet: {e}")

        # Capacity warning: at max droplets and queue still deep
        elif (
            depth > q_config["scale_up_threshold"] * 2
            and num_droplets >= q_config["max_droplets"]
        ):
            alerts.alert_capacity_warning(
                queue_name, depth, q_config["max_droplets"], num_droplets
            )

        # --- Scale DOWN ---
        if depth == 0 and num_droplets > 0:
            for droplet_id, info in list(state.get("droplets", {}).items()):
                if info.get("queue") != queue_name:
                    continue
                created = _parse_iso(info["created_at"])
                idle_seconds = (_now() - created).total_seconds()

                # Use last_queue_nonempty_at if tracked, otherwise fall back to created_at
                last_nonempty = info.get("last_queue_nonempty_at")
                if last_nonempty:
                    idle_seconds = (_now() - _parse_iso(last_nonempty)).total_seconds()

                if idle_seconds >= q_config["scale_down_idle_s"]:
                    success = do_client.destroy_droplet(int(droplet_id))
                    if success:
                        # Credit hours
                        hours = (_now() - created).total_seconds() / 3600
                        state["monthly_hours"] += hours * q_config.get("hourly_cost", 0.01)
                        del state["droplets"][droplet_id]
                        _save_state(state)

                        logger.info(f"SCALE DOWN: destroyed {info['name']} (idle {idle_seconds:.0f}s)")
                        alerts.alert_scale_down(info["name"], queue_name, idle_seconds)

                        if _HAS_PROMETHEUS:
                            scale_events_counter.labels(action="down", worker_type=worker_type).inc()

        # Track when queue was last non-empty (for idle detection)
        if depth > 0:
            for droplet_id, info in state.get("droplets", {}).items():
                if info.get("queue") == queue_name:
                    info["last_queue_nonempty_at"] = _iso(_now())


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    logger.info("Autoscaler starting")

    if not config.DO_API_TOKEN:
        logger.error("DIGITALOCEAN_API_TOKEN not set, exiting")
        sys.exit(1)

    if not config.MAIN_HOST_IP:
        logger.error("MAIN_HOST_IP not set (needed for droplet -> RabbitMQ), exiting")
        sys.exit(1)

    # Start Prometheus metrics server
    if _HAS_PROMETHEUS:
        try:
            start_http_server(9095)
            logger.info("Prometheus metrics on port 9095")
        except OSError as e:
            logger.warning(f"Could not start metrics server: {e}")

    state = _load_state()
    _reset_monthly_if_needed(state)
    _reconcile(state)
    _save_state(state)

    logger.info(
        f"Initialized: {_total_droplet_count(state)} active droplets, "
        f"monthly hours: {state.get('monthly_hours', 0):.1f}"
    )

    heartbeat_counter = 0
    HEARTBEAT_CYCLES = 10  # every 10 × 30s = 5 minutes

    while True:
        try:
            _reset_monthly_if_needed(state)

            queue_depths = rabbitmq_client.get_queue_depths()
            if queue_depths is None:
                time.sleep(config.POLL_INTERVAL_S)
                continue

            logger.debug(f"Queue depths: {queue_depths}")

            evaluate_and_act(state, queue_depths)
            _save_state(state)

            heartbeat_counter += 1
            if heartbeat_counter >= HEARTBEAT_CYCLES:
                logger.info(
                    f"Heartbeat: polling active, {_total_droplet_count(state)} managed droplets, "
                    f"monthly cost ~${_estimate_monthly_cost(state):.2f}"
                )
                heartbeat_counter = 0

        except Exception as e:
            logger.error(f"Autoscaler loop error: {e}", exc_info=True)
            alerts.alert_error(f"Autoscaler loop error: {e}")

        time.sleep(config.POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
