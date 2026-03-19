"""GCP Cloud Trace — read-only tracing configuration inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def get_trace_config() -> dict[str, Any]:
    """Return the project's Cloud Trace configuration."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("cloudtrace", "v2", credentials=credentials)
        # Cloud Trace v2 doesn't have a project-level "get config" endpoint,
        # so we list a small sample of recent traces to confirm it's active.
        result = service.projects().traces().list(
            parent=f"projects/{PROJECT}",
            pageSize=5,
        ).execute()
        traces = result.get("traces", [])
        return {
            "trace_api": "enabled",
            "recent_trace_count": len(traces),
            "sampling_active": len(traces) > 0,
            "note": "Cloud Trace is enabled. Recent trace data is present." if traces
                    else "Cloud Trace is enabled but no recent traces found — sampling may be off or no traffic yet.",
        }
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "api": "cloudtrace.googleapis.com",
    "display_name": "Cloud Trace",
    "domains": ["incident"],
    "tools": [get_trace_config],
}
