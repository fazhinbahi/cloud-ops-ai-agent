"""GCP Cloud Monitoring — read-only alert and health data."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_alert_policies() -> list[dict[str, Any]]:
    """List all Cloud Monitoring alert policies."""
    try:
        from google.cloud import monitoring_v3
        import google.auth
        credentials, _ = google.auth.default()
        client = monitoring_v3.AlertPolicyServiceClient(credentials=credentials)
        alerts = []
        for policy in client.list_alert_policies(name=f"projects/{PROJECT}"):
            alerts.append({
                "name": policy.name.split("/")[-1],
                "display_name": policy.display_name,
                "enabled": policy.enabled.value if hasattr(policy.enabled, "value") else policy.enabled,
                "conditions": [c.display_name for c in policy.conditions],
            })
        return alerts
    except Exception as e:
        return [{"error": str(e)}]


def list_uptime_checks() -> list[dict[str, Any]]:
    """List Cloud Monitoring uptime check configurations."""
    try:
        from google.cloud import monitoring_v3
        import google.auth
        credentials, _ = google.auth.default()
        client = monitoring_v3.UptimeCheckServiceClient(credentials=credentials)
        return [{
            "name": uc.display_name,
            "resource_type": uc.monitored_resource.type if uc.monitored_resource else "unknown",
        } for uc in client.list_uptime_check_configs(parent=f"projects/{PROJECT}")]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "monitoring.googleapis.com",
    "display_name": "Cloud Monitoring",
    "domains": ["incident"],
    "tools": [list_alert_policies, list_uptime_checks],
}
