"""GCP Cloud Data Fusion — read-only instance inspection.

Adding this file is ALL that's needed to make Data Fusion appear
in the data agent's observation cycle. No other files need changing.
"""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_data_fusion_instances() -> list[dict[str, Any]]:
    """List all Cloud Data Fusion instances and their health state."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("datafusion", "v1", credentials=credentials)
        result = service.projects().locations().instances().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": i.get("name", "").split("/")[-1],
            "state": i.get("state"),           # RUNNING, FAILED, CREATING, etc.
            "type": i.get("type"),             # BASIC, ENTERPRISE, DEVELOPER
            "version": i.get("version"),
            "region": i.get("name", "").split("/")[3] if "/" in i.get("name", "") else "",
            "enable_stackdriver_logging": i.get("enableStackdriverLogging"),
            "enable_stackdriver_monitoring": i.get("enableStackdriverMonitoring"),
            "state_message": i.get("stateMessage", ""),
        } for i in result.get("instances", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_data_fusion_pipelines() -> list[dict[str, Any]]:
    """
    List pipelines across all Data Fusion instances.
    Uses the Data Fusion REST API (not Discovery API).
    """
    try:
        instances = list_data_fusion_instances()
        if not instances or "error" in instances[0]:
            return [{"note": "No Data Fusion instances found or API not enabled."}]

        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()

        pipelines = []
        for inst in instances:
            if inst.get("state") != "RUNNING":
                continue
            # Data Fusion pipelines are accessed via its internal REST endpoint
            pipelines.append({
                "instance": inst["name"],
                "note": "Pipeline listing requires Data Fusion instance REST endpoint access.",
            })
        return pipelines
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "datafusion.googleapis.com",
    "display_name": "Cloud Data Fusion",
    "domains": ["data"],
    "tools": [list_data_fusion_instances, list_data_fusion_pipelines],
}
