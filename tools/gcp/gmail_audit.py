"""
Gmail API audit — flags the unusual presence of gmail.googleapis.com
being enabled in a GCP project.

Gmail API should almost never be enabled on an infrastructure project.
Its presence is a security signal worth investigating.
This module doesn't call Gmail (no useful cloud infra data there);
it just surfaces the finding for the security agent.
"""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def check_gmail_api_enabled() -> dict[str, Any]:
    """
    Confirm whether gmail.googleapis.com is enabled and surface it as
    a security signal. Gmail API on an infra project indicates either:
    - A forgotten OAuth app using project credentials
    - Accidental enablement
    - Deliberate data exfiltration setup (worst case)
    """
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("serviceusage", "v1", credentials=credentials)
        result = service.services().get(
            name=f"projects/{PROJECT}/services/gmail.googleapis.com"
        ).execute()
        state = result.get("state", "UNKNOWN")
        return {
            "api": "gmail.googleapis.com",
            "state": state,
            "warning": (
                "Gmail API is enabled on this GCP project. "
                "This API should not be enabled on infrastructure/cloud-ops projects. "
                "Investigate: which OAuth client or service account is using it, and why."
            ) if state == "ENABLED" else "Gmail API is not enabled.",
        }
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "api": "gmail.googleapis.com",
    "display_name": "Gmail API (Unexpected — Security Signal)",
    "domains": ["security"],
    "tools": [check_gmail_api_enabled],
}
