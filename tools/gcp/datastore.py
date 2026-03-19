"""GCP Cloud Datastore / Firestore in Datastore mode — read-only inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def get_datastore_info() -> dict[str, Any]:
    """Return Datastore configuration and index count."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("datastore", "v1", credentials=credentials)

        # List indexes
        result = service.projects().indexes().list(projectId=PROJECT).execute()
        indexes = result.get("indexes", [])
        ready = [i for i in indexes if i.get("state") == "READY"]
        building = [i for i in indexes if i.get("state") == "CREATING"]

        return {
            "total_indexes": len(indexes),
            "ready_indexes": len(ready),
            "building_indexes": len(building),
            "building_index_names": [i.get("indexId") for i in building],
            "note": "Entity counts require a query — not available in read-only mode.",
        }
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "api": "datastore.googleapis.com",
    "display_name": "Cloud Datastore",
    "domains": ["infra"],
    "tools": [get_datastore_info],
}
