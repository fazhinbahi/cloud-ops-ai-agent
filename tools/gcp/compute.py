"""GCP Compute Engine — read-only data collection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_compute_instances() -> list[dict[str, Any]]:
    """List all Compute Engine VM instances across all zones."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        result = service.instances().aggregatedList(project=PROJECT).execute()
        instances = []
        for zone_data in result.get("items", {}).values():
            for inst in zone_data.get("instances", []):
                instances.append({
                    "name": inst.get("name"),
                    "zone": inst.get("zone", "").split("/")[-1],
                    "machine_type": inst.get("machineType", "").split("/")[-1],
                    "status": inst.get("status"),
                    "creation_timestamp": inst.get("creationTimestamp"),
                    "tags": inst.get("tags", {}).get("items", []),
                })
        return instances
    except Exception as e:
        return [{"error": str(e)}]


def list_idle_compute_instances() -> list[dict[str, Any]]:
    """Return TERMINATED or SUSPENDED instances (idle / wasted spend)."""
    try:
        return [i for i in list_compute_instances()
                if i.get("status") in ("TERMINATED", "SUSPENDED")]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "compute.googleapis.com",
    "display_name": "Compute Engine",
    "domains": ["infra", "cost"],
    "tools": [list_compute_instances, list_idle_compute_instances],
}
