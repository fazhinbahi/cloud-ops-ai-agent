"""GCP Dataplex — read-only data lake and asset inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_dataplex_lakes() -> list[dict[str, Any]]:
    """List Dataplex lakes and their state."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("dataplex", "v1", credentials=credentials)
        result = service.projects().locations().lakes().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": lake.get("name", "").split("/")[-1],
            "display_name": lake.get("displayName", ""),
            "state": lake.get("state"),
            "region": lake.get("name", "").split("/")[3] if "/" in lake.get("name", "") else "",
            "asset_status": lake.get("assetStatus", {}),
        } for lake in result.get("lakes", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_dataplex_data_scans() -> list[dict[str, Any]]:
    """List Dataplex data quality and data profile scans."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("dataplex", "v1", credentials=credentials)
        result = service.projects().locations().dataScans().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": scan.get("name", "").split("/")[-1],
            "type": scan.get("type"),
            "state": scan.get("state"),
            "data_source": scan.get("data", {}).get("resource", ""),
            "execution_status": scan.get("executionStatus", {}).get("latestJobResult", {}).get("state", ""),
        } for scan in result.get("dataScans", [])]
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "dataplex.googleapis.com",
    "display_name": "Dataplex",
    "domains": ["data"],
    "tools": [list_dataplex_lakes, list_dataplex_data_scans],
}
