"""GCP Cloud Storage — read-only bucket auditing."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_public_gcs_buckets() -> list[dict[str, Any]]:
    """List GCS buckets with public (allUsers/allAuthenticatedUsers) IAM bindings."""
    try:
        from google.cloud import storage
        import google.auth
        credentials, _ = google.auth.default()
        client = storage.Client(project=PROJECT, credentials=credentials)
        public_buckets = []
        for bucket in client.list_buckets():
            try:
                policy = bucket.get_iam_policy(requested_policy_version=3)
                for binding in policy.bindings:
                    members = binding.get("members", [])
                    if "allUsers" in members or "allAuthenticatedUsers" in members:
                        public_buckets.append({
                            "bucket": bucket.name,
                            "role": binding.get("role"),
                            "public_members": [m for m in members if "all" in m],
                        })
                        break
            except Exception:
                pass
        return public_buckets
    except Exception as e:
        return [{"error": str(e)}]


def list_all_buckets() -> list[dict[str, Any]]:
    """List all GCS buckets with basic metadata."""
    try:
        from google.cloud import storage
        import google.auth
        credentials, _ = google.auth.default()
        client = storage.Client(project=PROJECT, credentials=credentials)
        return [{
            "name": b.name,
            "location": b.location,
            "storage_class": b.storage_class,
            "versioning_enabled": b.versioning_enabled,
        } for b in client.list_buckets()]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "storage.googleapis.com",
    "display_name": "Cloud Storage",
    "domains": ["security"],
    "tools": [list_public_gcs_buckets, list_all_buckets],
}
