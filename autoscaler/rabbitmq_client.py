"""RabbitMQ management API client for queue depth monitoring."""

import logging

import requests

from config import RABBITMQ_MGMT_URL, RABBITMQ_MGMT_USER, RABBITMQ_MGMT_PASS, SCALABLE_QUEUES

logger = logging.getLogger(__name__)


def get_queue_depths():
    """Get message counts for all scalable queues.

    Returns:
        dict: {queue_name: messages_ready} for queues in SCALABLE_QUEUES.
              Returns 0 for queues that don't exist yet in RabbitMQ.
    """
    try:
        resp = requests.get(
            f"{RABBITMQ_MGMT_URL}/api/queues/%2f",
            auth=(RABBITMQ_MGMT_USER, RABBITMQ_MGMT_PASS),
            timeout=5,
        )
        resp.raise_for_status()
        queues = resp.json()
    except requests.RequestException as e:
        logger.error(f"Failed to fetch queue depths: {e}")
        raise

    depth_map = {name: 0 for name in SCALABLE_QUEUES}
    for q in queues:
        name = q.get("name")
        if name in depth_map:
            depth_map[name] = q.get("messages_ready", 0)

    return depth_map


def get_queue_consumers(queue_name):
    """Get the number of active consumers for a specific queue.

    Returns:
        int: Number of consumers, or 0 on error.
    """
    try:
        resp = requests.get(
            f"{RABBITMQ_MGMT_URL}/api/queues/%2f/{queue_name}",
            auth=(RABBITMQ_MGMT_USER, RABBITMQ_MGMT_PASS),
            timeout=5,
        )
        if resp.status_code == 404:
            return 0
        resp.raise_for_status()
        return resp.json().get("consumers", 0)
    except requests.RequestException as e:
        logger.warning(f"Failed to get consumers for {queue_name}: {e}")
        return 0
