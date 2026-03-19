"""GCP BigQuery — read-only dataset and table inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_bigquery_datasets() -> list[dict[str, Any]]:
    """List all BigQuery datasets in the project."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("bigquery", "v2", credentials=credentials)
        result = service.datasets().list(projectId=PROJECT).execute()
        datasets = []
        for ds in result.get("datasets", []):
            ref = ds.get("datasetReference", {})
            datasets.append({
                "dataset_id": ref.get("datasetId"),
                "location": ds.get("location"),
                "friendly_name": ds.get("friendlyName", ""),
            })
        return datasets
    except Exception as e:
        return [{"error": str(e)}]


def list_bigquery_jobs() -> list[dict[str, Any]]:
    """List recent BigQuery jobs (last 20) to detect failures or long-running queries."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("bigquery", "v2", credentials=credentials)
        result = service.jobs().list(
            projectId=PROJECT,
            maxResults=20,
            allUsers=True,
        ).execute()
        jobs = []
        for job in result.get("jobs", []):
            status = job.get("status", {})
            config = job.get("configuration", {})
            jobs.append({
                "job_id": job.get("id", "").split(":")[-1],
                "state": status.get("state"),
                "error": status.get("errorResult", {}).get("message", ""),
                "job_type": list(config.keys())[0] if config else "unknown",
                "creation_time": job.get("statistics", {}).get("creationTime"),
            })
        return jobs
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "bigquery.googleapis.com",
    "display_name": "BigQuery",
    "domains": ["data"],
    "tools": [list_bigquery_datasets, list_bigquery_jobs],
}
