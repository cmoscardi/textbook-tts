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
    level=logging.DEBUG,
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
        worker_type = info.get("worker_type", "")
        w_config = config.SCALABLE_WORKERS.get(worker_type, {})
        hourly = w_config.get("hourly_cost", 0.01)
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
        w_config = config.SCALABLE_WORKERS.get(info.get("worker_type", ""), {})
        state["monthly_hours"] += hours * w_config.get("hourly_cost", 0.01)

    # Adopt droplets on DO that aren't in our state (e.g. created before crash)
    for d in actual:
        if str(d.id) not in state.get("droplets", {}):
            # Identify the worker group from tags (worker_type is the grouping key)
            worker_type = ""
            for tag in d.tags:
                if tag.startswith("worker-type:"):
                    worker_type = tag.split(":", 1)[1]
            logger.warning(f"Reconcile: adopting orphaned droplet {d.name} ({d.id})")
            state.setdefault("droplets", {})[str(d.id)] = {
                "name": d.name,
                "worker_type": worker_type,
                "created_at": _iso(_now()),  # approximate
            }


# ---------------------------------------------------------------------------
# Cloud-init generation
# ---------------------------------------------------------------------------

def _make_user_data(worker_type, converter_workers=5):
    """Generate cloud-init user data for a droplet.

    converter_workers sets how many solo TTS worker processes the converter droplet runs
    (ignored by non-converter workers); sourced from the worker's remote_concurrency.
    """
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
CONVERTER_WORKERS={converter_workers}
WORKER_TYPE={worker_type}
ENVEOF

# Source env and start the worker
set -a; source /etc/environment; set +a
/opt/autoscaler/start-worker.sh
"""


# ---------------------------------------------------------------------------
# Scaling decisions
# ---------------------------------------------------------------------------

def _count_droplets_for_worker(state, worker_type):
    return sum(
        1 for info in state.get("droplets", {}).values()
        if info.get("worker_type") == worker_type
    )


def _total_droplet_count(state):
    return len(state.get("droplets", {}))


def _cooldown_elapsed(state, worker_type, cooldown_s):
    last = state.get("last_scale_up", {}).get(worker_type)
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

    for worker_type, w_config in config.SCALABLE_WORKERS.items():
        queues = w_config["queues"]
        # Combined backlog across every queue this worker serves.
        combined_depth = sum(queue_depths.get(q, 0) for q in queues)
        # Work-seconds weighted by each queue's avg task duration (heterogeneous tasks).
        total_work_s = sum(
            queue_depths.get(q, 0) * qc["task_duration_avg_s"]
            for q, qc in queues.items()
        )
        num_droplets = _count_droplets_for_worker(state, worker_type)
        # Representative queue used for tagging / alert context.
        primary_queue = next(iter(queues))

        if _HAS_PROMETHEUS:
            active_droplets_gauge.labels(worker_type=worker_type).set(num_droplets)

        # --- Scale UP ---
        total_concurrency = (
            w_config["local_concurrency"]
            + num_droplets * w_config["remote_concurrency"]
        )
        time_to_drain = total_work_s / max(total_concurrency, 1)

        if (
            combined_depth > w_config["scale_up_threshold"]
            and time_to_drain > 5
            and num_droplets < w_config["max_droplets"]
            and _total_droplet_count(state) < config.GLOBAL_MAX_DROPLETS
            and _cooldown_elapsed(state, worker_type, w_config["cooldown_s"])
            and monthly_cost < config.MONTHLY_COST_CAP_USD
            and w_config["snapshot_id"]
        ):
            try:
                droplet = do_client.create_droplet(
                    worker_type=worker_type,
                    queue_name=primary_queue,
                    snapshot_id=w_config["snapshot_id"],
                    size=w_config["droplet_size"],
                    user_data=_make_user_data(worker_type, w_config["remote_concurrency"]),
                )
                state.setdefault("droplets", {})[str(droplet.id)] = {
                    "name": droplet.name,
                    "worker_type": worker_type,
                    "created_at": _iso(_now()),
                }
                state.setdefault("last_scale_up", {})[worker_type] = _iso(_now())
                _save_state(state)

                logger.info(f"SCALE UP: created {droplet.name} for {worker_type} (depth={combined_depth})")
                alerts.alert_scale_up(droplet.name, worker_type, combined_depth)

                if _HAS_PROMETHEUS:
                    scale_events_counter.labels(action="up", worker_type=worker_type).inc()

            except Exception as e:
                logger.error(f"Failed to scale up {worker_type}: {e}")
                alerts.alert_error(f"Failed to create {worker_type} droplet: {e}")

        # Capacity warning: at max droplets and backlog still deep
        elif (
            combined_depth > w_config["scale_up_threshold"] * 2
            and num_droplets >= w_config["max_droplets"]
        ):
            alerts.alert_capacity_warning(
                worker_type, combined_depth, w_config["max_droplets"], num_droplets
            )

        # --- Scale DOWN --- (only when ALL of the worker's queues are empty)
        if combined_depth == 0 and num_droplets > 0:
            for droplet_id, info in list(state.get("droplets", {}).items()):
                if info.get("worker_type") != worker_type:
                    continue
                created = _parse_iso(info["created_at"])
                idle_seconds = (_now() - created).total_seconds()

                # Use last_queue_nonempty_at if tracked, otherwise fall back to created_at
                last_nonempty = info.get("last_queue_nonempty_at")
                if last_nonempty:
                    idle_seconds = (_now() - _parse_iso(last_nonempty)).total_seconds()

                if idle_seconds >= w_config["scale_down_idle_s"]:
                    success = do_client.destroy_droplet(int(droplet_id))
                    if success:
                        # Credit hours
                        hours = (_now() - created).total_seconds() / 3600
                        state["monthly_hours"] += hours * w_config.get("hourly_cost", 0.01)
                        del state["droplets"][droplet_id]
                        _save_state(state)

                        logger.info(f"SCALE DOWN: destroyed {info['name']} (idle {idle_seconds:.0f}s)")
                        alerts.alert_scale_down(info["name"], worker_type, idle_seconds)

                        if _HAS_PROMETHEUS:
                            scale_events_counter.labels(action="down", worker_type=worker_type).inc()

        # Track when this worker's queues were last non-empty (for idle detection)
        if combined_depth > 0:
            for droplet_id, info in state.get("droplets", {}).items():
                if info.get("worker_type") == worker_type:
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
