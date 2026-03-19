"""GCP Cloud Billing — read-only billing info."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def get_billing_info() -> dict[str, Any]:
    """Return billing account status linked to this project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("cloudbilling", "v1", credentials=credentials)
        info = service.projects().getBillingInfo(
            name=f"projects/{PROJECT}"
        ).execute()
        return {
            "billing_account": info.get("billingAccountName", ""),
            "billing_enabled": info.get("billingEnabled", False),
            "note": "Detailed cost breakdown requires BigQuery billing export.",
        }
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "api": "cloudbilling.googleapis.com",
    "display_name": "Cloud Billing",
    "domains": ["cost"],
    "tools": [get_billing_info],
}
