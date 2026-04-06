"""DigitalOcean API client for droplet lifecycle management."""

import logging
import uuid
from dataclasses import dataclass

import requests

from config import DO_API_TOKEN, DO_REGION, DO_SSH_KEY_FINGERPRINT, MANAGED_TAG

logger = logging.getLogger(__name__)

API_BASE = "https://api.digitalocean.com/v2"


def _headers():
    return {
        "Authorization": f"Bearer {DO_API_TOKEN}",
        "Content-Type": "application/json",
    }


@dataclass
class Droplet:
    id: int
    name: str
    status: str
    ip_address: str
    tags: list


def create_droplet(worker_type, queue_name, snapshot_id, size, user_data):
    """Create a new droplet from a snapshot.

    Args:
        worker_type: e.g. 'fast-parser', 'converter'
        queue_name: e.g. 'fast_parse_queue'
        snapshot_id: DO snapshot ID (numeric string)
        size: DO droplet size slug
        user_data: cloud-init user data string

    Returns:
        Droplet with id, name, status, ip_address, tags

    Raises:
        requests.RequestException on API errors
    """
    short_id = uuid.uuid4().hex[:8]
    name = f"autoscaler-{worker_type}-{short_id}"

    tags = [MANAGED_TAG, f"worker-type:{worker_type}", f"queue:{queue_name}"]

    payload = {
        "name": name,
        "region": DO_REGION,
        "size": size,
        "image": int(snapshot_id),
        "user_data": user_data,
        "tags": tags,
        "monitoring": True,
    }

    if DO_SSH_KEY_FINGERPRINT:
        payload["ssh_keys"] = [DO_SSH_KEY_FINGERPRINT]

    logger.info(f"Creating droplet {name} (size={size}, region={DO_REGION})")
    resp = requests.post(f"{API_BASE}/droplets", json=payload, headers=_headers(), timeout=30)
    resp.raise_for_status()

    data = resp.json()["droplet"]
    return Droplet(
        id=data["id"],
        name=data["name"],
        status=data["status"],
        ip_address="",  # not assigned yet at creation time
        tags=data.get("tags", []),
    )


def destroy_droplet(droplet_id):
    """Destroy a droplet by ID. Billing stops immediately.

    Returns:
        True on success, False on error.
    """
    logger.info(f"Destroying droplet {droplet_id}")
    try:
        resp = requests.delete(
            f"{API_BASE}/droplets/{droplet_id}",
            headers=_headers(),
            timeout=30,
        )
        if resp.status_code == 204:
            return True
        logger.error(f"Destroy droplet {droplet_id} returned {resp.status_code}: {resp.text}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to destroy droplet {droplet_id}: {e}")
        return False


def list_managed_droplets():
    """List all droplets tagged with MANAGED_TAG.

    Returns:
        list[Droplet]
    """
    try:
        resp = requests.get(
            f"{API_BASE}/droplets",
            params={"tag_name": MANAGED_TAG, "per_page": 100},
            headers=_headers(),
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Failed to list managed droplets: {e}")
        return []

    droplets = []
    for d in resp.json().get("droplets", []):
        ip = ""
        for net in d.get("networks", {}).get("v4", []):
            if net.get("type") == "public":
                ip = net.get("ip_address", "")
                break
        droplets.append(Droplet(
            id=d["id"],
            name=d["name"],
            status=d["status"],
            ip_address=ip,
            tags=d.get("tags", []),
        ))

    return droplets


def get_droplets_for_queue(queue_name):
    """Filter managed droplets by queue tag.

    Returns:
        list[Droplet]
    """
    all_droplets = list_managed_droplets()
    tag = f"queue:{queue_name}"
    return [d for d in all_droplets if tag in d.tags]
