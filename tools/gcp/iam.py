"""GCP IAM — read-only policy and service account auditing."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_project_iam_bindings() -> list[dict[str, Any]]:
    """List all IAM role bindings on the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("cloudresourcemanager", "v1", credentials=credentials)
        result = service.projects().getIamPolicy(
            resource=PROJECT, body={}
        ).execute()
        return [{
            "role": b.get("role"),
            "members": b.get("members", []),
        } for b in result.get("bindings", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_service_accounts() -> list[dict[str, Any]]:
    """List all service accounts in the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("iam", "v1", credentials=credentials)
        result = service.projects().serviceAccounts().list(
            name=f"projects/{PROJECT}"
        ).execute()
        return [{
            "email": sa.get("email"),
            "display_name": sa.get("displayName"),
            "disabled": sa.get("disabled", False),
        } for sa in result.get("accounts", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "iam.googleapis.com",
    "display_name": "IAM & Admin",
    "domains": ["security"],
    "tools": [list_project_iam_bindings, list_service_accounts],
}
