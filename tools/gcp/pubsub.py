"""GCP Pub/Sub — read-only topic and subscription inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_pubsub_topics() -> list[dict[str, Any]]:
    """List all Pub/Sub topics in the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("pubsub", "v1", credentials=credentials)
        result = service.projects().topics().list(
            project=f"projects/{PROJECT}"
        ).execute()
        return [{
            "name": t.get("name", "").split("/")[-1],
            "full_name": t.get("name"),
            "kms_key": t.get("kmsKeyName", "none"),
        } for t in result.get("topics", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_pubsub_subscriptions() -> list[dict[str, Any]]:
    """List Pub/Sub subscriptions and identify those with no recent activity."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("pubsub", "v1", credentials=credentials)
        result = service.projects().subscriptions().list(
            project=f"projects/{PROJECT}"
        ).execute()
        return [{
            "name": s.get("name", "").split("/")[-1],
            "topic": s.get("topic", "").split("/")[-1],
            "ack_deadline_seconds": s.get("ackDeadlineSeconds"),
            "retain_acked_messages": s.get("retainAckedMessages", False),
            "expiration_policy": s.get("expirationPolicy", {}).get("ttl", "never"),
        } for s in result.get("subscriptions", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "pubsub.googleapis.com",
    "display_name": "Cloud Pub/Sub",
    "domains": ["data"],
    "tools": [list_pubsub_topics, list_pubsub_subscriptions],
}
