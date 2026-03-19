"""GCP BigQuery extended APIs — connections, data transfer, reservations, analytics hub."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_bigquery_connections() -> list[dict[str, Any]]:
    """List BigQuery external data connections (to Cloud SQL, Spanner, etc.)."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("bigqueryconnection", "v1", credentials=credentials)
        result = service.projects().locations().connections().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": c.get("name", "").split("/")[-1],
            "friendly_name": c.get("friendlyName", ""),
            "connection_type": list(set(c.keys()) - {"name", "friendlyName", "description", "creationTime", "lastModifiedTime", "hasCredential"}),
            "has_credential": c.get("hasCredential", False),
        } for c in result.get("connections", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_bigquery_transfer_configs() -> list[dict[str, Any]]:
    """List BigQuery Data Transfer scheduled jobs and their last run status."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("bigquerydatatransfer", "v1", credentials=credentials)
        result = service.projects().locations().transferConfigs().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": t.get("displayName", ""),
            "data_source": t.get("dataSourceId", ""),
            "state": t.get("state"),
            "schedule": t.get("schedule", ""),
            "destination_dataset": t.get("destinationDatasetId", ""),
            "disabled": t.get("disabled", False),
        } for t in result.get("transferConfigs", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_bigquery_reservations() -> list[dict[str, Any]]:
    """List BigQuery slot reservations and commitments (affects cost)."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("bigqueryreservation", "v1", credentials=credentials)

        # List reservations
        res_result = service.projects().locations().reservations().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        reservations = [{
            "name": r.get("name", "").split("/")[-1],
            "slot_capacity": r.get("slotCapacity", 0),
            "ignore_idle_slots": r.get("ignoreIdleSlots", False),
        } for r in res_result.get("reservations", [])]

        # List capacity commitments (monthly/annual spend)
        commit_result = service.projects().locations().capacityCommitments().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        commitments = [{
            "name": c.get("name", "").split("/")[-1],
            "slot_count": c.get("slotCount", 0),
            "plan": c.get("plan"),
            "state": c.get("state"),
        } for c in commit_result.get("capacityCommitments", [])]

        return {"reservations": reservations, "capacity_commitments": commitments}
    except Exception as e:
        return [{"error": str(e)}]


def list_analytics_hub_exchanges() -> list[dict[str, Any]]:
    """List Analytics Hub data exchanges (data sharing configurations)."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("analyticshub", "v1", credentials=credentials)
        result = service.projects().locations().dataExchanges().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": e.get("name", "").split("/")[-1],
            "display_name": e.get("displayName", ""),
            "listing_count": e.get("listingCount", 0),
            "primary_contact": e.get("primaryContact", ""),
        } for e in result.get("dataExchanges", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "bigqueryconnection.googleapis.com",   # representative API for the group
    "display_name": "BigQuery Extended (Connections, Transfers, Reservations, Analytics Hub)",
    "domains": ["data", "cost"],
    "tools": [
        list_bigquery_connections,
        list_bigquery_transfer_configs,
        list_bigquery_reservations,
        list_analytics_hub_exchanges,
    ],
}
