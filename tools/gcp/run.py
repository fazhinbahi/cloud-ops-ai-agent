"""GCP Cloud Run — read-only service inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_cloud_run_services() -> list[dict[str, Any]]:
    """List all Cloud Run services and their latest revision status."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("run", "v1", credentials=credentials)
        regions = ["us-central1", "us-east1", "us-west1", "europe-west1", "asia-east1"]
        for region in regions:
            try:
                result = service.namespaces().services().list(
                    parent=f"namespaces/{PROJECT}"
                ).execute()
                services = []
                for svc in result.get("items", []):
                    meta = svc.get("metadata", {})
                    status = svc.get("status", {})
                    conditions = status.get("conditions", [])
                    ready = next(
                        (c.get("status") for c in conditions if c.get("type") == "Ready"),
                        "Unknown",
                    )
                    services.append({
                        "name": meta.get("name"),
                        "ready": ready,
                        "url": status.get("url"),
                        "latest_revision": status.get("latestReadyRevisionName"),
                    })
                return services
            except Exception:
                continue
        return []
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "run.googleapis.com",
    "display_name": "Cloud Run",
    "domains": ["deployment"],
    "tools": [list_cloud_run_services],
}
