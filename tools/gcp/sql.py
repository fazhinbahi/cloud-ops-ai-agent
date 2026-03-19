"""GCP Cloud SQL — read-only data collection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_cloud_sql_instances() -> list[dict[str, Any]]:
    """List all Cloud SQL instances."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("sqladmin", "v1beta4", credentials=credentials)
        result = service.instances().list(project=PROJECT).execute()
        return [{
            "name": inst.get("name"),
            "database_version": inst.get("databaseVersion"),
            "tier": inst.get("settings", {}).get("tier"),
            "state": inst.get("state"),
            "region": inst.get("region"),
            "backup_enabled": inst.get("settings", {}).get("backupConfiguration", {}).get("enabled"),
        } for inst in result.get("items", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "sqladmin.googleapis.com",
    "display_name": "Cloud SQL",
    "domains": ["infra"],
    "tools": [list_cloud_sql_instances],
}
