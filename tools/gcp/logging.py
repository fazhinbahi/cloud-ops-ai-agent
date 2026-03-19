"""GCP Cloud Logging — read-only log sink, metric, and exclusion inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_log_sinks() -> list[dict[str, Any]]:
    """List log sinks — where logs are being exported."""
    try:
        from google.cloud import logging as gcp_logging
        import google.auth
        credentials, _ = google.auth.default()
        client = gcp_logging.Client(project=PROJECT, credentials=credentials)
        return [{
            "name": sink.name,
            "destination": sink.destination,
            "filter": sink.filter_,
            "disabled": getattr(sink, "disabled", False),
        } for sink in client.list_sinks()]
    except Exception as e:
        return [{"error": str(e)}]


def list_log_based_metrics() -> list[dict[str, Any]]:
    """List log-based metrics (used for alerting on log patterns)."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("logging", "v2", credentials=credentials)
        result = service.projects().metrics().list(
            parent=f"projects/{PROJECT}"
        ).execute()
        return [{
            "name": m.get("name"),
            "description": m.get("description", ""),
            "filter": m.get("filter", ""),
        } for m in result.get("metrics", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_log_exclusions() -> list[dict[str, Any]]:
    """List log exclusions — what's being deliberately dropped."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("logging", "v2", credentials=credentials)
        result = service.projects().exclusions().list(
            parent=f"projects/{PROJECT}"
        ).execute()
        return [{
            "name": e.get("name"),
            "filter": e.get("filter"),
            "disabled": e.get("disabled", False),
        } for e in result.get("exclusions", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "logging.googleapis.com",
    "display_name": "Cloud Logging",
    "domains": ["incident", "security"],
    "tools": [list_log_sinks, list_log_based_metrics, list_log_exclusions],
}
