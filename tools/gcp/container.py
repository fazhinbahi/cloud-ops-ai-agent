"""GCP Kubernetes Engine (GKE) — read-only data collection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_gke_clusters() -> list[dict[str, Any]]:
    """List all GKE clusters in the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("container", "v1", credentials=credentials)
        result = service.projects().locations().clusters().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": c.get("name"),
            "location": c.get("location"),
            "status": c.get("status"),
            "node_count": c.get("currentNodeCount"),
            "k8s_version": c.get("currentMasterVersion"),
            "create_time": c.get("createTime"),
        } for c in result.get("clusters", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "container.googleapis.com",
    "display_name": "Google Kubernetes Engine",
    "domains": ["infra"],
    "tools": [list_gke_clusters],
}
