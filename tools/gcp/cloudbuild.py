"""GCP Cloud Build — read-only build history inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_recent_builds() -> list[dict[str, Any]]:
    """List recent Cloud Build builds and their statuses."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("cloudbuild", "v1", credentials=credentials)
        result = service.projects().builds().list(
            projectId=PROJECT,
            pageSize=20,
        ).execute()
        return [{
            "id": b.get("id"),
            "status": b.get("status"),
            "trigger_id": b.get("buildTriggerId"),
            "start_time": b.get("startTime"),
            "finish_time": b.get("finishTime"),
            "source": b.get("source", {}).get("repoSource", {}).get("repoName", "unknown"),
        } for b in result.get("builds", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_build_triggers() -> list[dict[str, Any]]:
    """List Cloud Build triggers configured in the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("cloudbuild", "v1", credentials=credentials)
        result = service.projects().triggers().list(projectId=PROJECT).execute()
        return [{
            "id": t.get("id"),
            "name": t.get("name"),
            "description": t.get("description"),
            "disabled": t.get("disabled", False),
            "tags": t.get("tags", []),
        } for t in result.get("triggers", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "cloudbuild.googleapis.com",
    "display_name": "Cloud Build",
    "domains": ["deployment"],
    "tools": [list_recent_builds, list_build_triggers],
}
