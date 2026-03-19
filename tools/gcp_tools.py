"""
tools/gcp_tools.py — Read-only GCP data collection wrappers.

All functions return plain dicts/lists so agents can serialize them to JSON
and pass them to Claude for analysis.  No writes, no mutations.
"""

from __future__ import annotations

import os
from typing import Any

from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


# ─────────────────────────────────────────────
# Infrastructure
# ─────────────────────────────────────────────

def list_compute_instances() -> list[dict[str, Any]]:
    """List all Compute Engine instances across all zones."""
    try:
        from googleapiclient import discovery
        from google.oauth2 import service_account
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        result = service.instances().aggregatedList(project=PROJECT).execute()
        instances = []
        for zone_data in result.get("items", {}).values():
            for inst in zone_data.get("instances", []):
                instances.append({
                    "name": inst.get("name"),
                    "zone": inst.get("zone", "").split("/")[-1],
                    "machine_type": inst.get("machineType", "").split("/")[-1],
                    "status": inst.get("status"),
                    "creation_timestamp": inst.get("creationTimestamp"),
                    "tags": inst.get("tags", {}).get("items", []),
                })
        return instances
    except Exception as e:
        return [{"error": str(e)}]


def list_gke_clusters() -> list[dict[str, Any]]:
    """List all GKE clusters in the project."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("container", "v1", credentials=credentials)
        result = service.projects().locations().clusters().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        clusters = []
        for c in result.get("clusters", []):
            clusters.append({
                "name": c.get("name"),
                "location": c.get("location"),
                "status": c.get("status"),
                "node_count": c.get("currentNodeCount"),
                "k8s_version": c.get("currentMasterVersion"),
                "create_time": c.get("createTime"),
            })
        return clusters
    except Exception as e:
        return [{"error": str(e)}]


def list_cloud_sql_instances() -> list[dict[str, Any]]:
    """List all Cloud SQL instances."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("sqladmin", "v1beta4", credentials=credentials)
        result = service.instances().list(project=PROJECT).execute()
        instances = []
        for inst in result.get("items", []):
            instances.append({
                "name": inst.get("name"),
                "database_version": inst.get("databaseVersion"),
                "tier": inst.get("settings", {}).get("tier"),
                "state": inst.get("state"),
                "region": inst.get("region"),
            })
        return instances
    except Exception as e:
        return [{"error": str(e)}]


def list_vpc_networks() -> list[dict[str, Any]]:
    """List VPC networks and their subnets."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        result = service.networks().list(project=PROJECT).execute()
        networks = []
        for net in result.get("items", []):
            networks.append({
                "name": net.get("name"),
                "auto_create_subnetworks": net.get("autoCreateSubnetworks"),
                "subnetworks": [s.split("/")[-1] for s in net.get("subnetworks", [])],
                "creation_timestamp": net.get("creationTimestamp"),
            })
        return networks
    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────
# Cost
# ─────────────────────────────────────────────

def get_billing_recent_costs() -> dict[str, Any]:
    """
    Return recent cost data from Cloud Billing (Budget API).
    Falls back to a summary if the Billing API is not enabled.
    """
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("cloudbilling", "v1", credentials=credentials)

        # Get billing account linked to project
        billing_info = service.projects().getBillingInfo(
            name=f"projects/{PROJECT}"
        ).execute()

        billing_account = billing_info.get("billingAccountName", "")
        enabled = billing_info.get("billingEnabled", False)

        return {
            "billing_account": billing_account,
            "billing_enabled": enabled,
            "note": "Detailed cost breakdown requires BigQuery billing export. "
                    "Enable it at: console.cloud.google.com/billing",
        }
    except Exception as e:
        return {"error": str(e)}


def list_idle_compute_instances() -> list[dict[str, Any]]:
    """
    Return TERMINATED or SUSPENDED instances (idle / wasted spend).
    """
    try:
        instances = list_compute_instances()
        return [
            i for i in instances
            if i.get("status") in ("TERMINATED", "SUSPENDED")
        ]
    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────
# Security
# ─────────────────────────────────────────────

def list_public_gcs_buckets() -> list[dict[str, Any]]:
    """List GCS buckets that have public (allUsers/allAuthenticatedUsers) IAM bindings."""
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


def list_open_firewall_rules() -> list[dict[str, Any]]:
    """List firewall rules that allow traffic from 0.0.0.0/0 or ::/0 (open to internet)."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        result = service.firewalls().list(project=PROJECT).execute()
        open_rules = []
        for rule in result.get("items", []):
            source_ranges = rule.get("sourceRanges", [])
            if "0.0.0.0/0" in source_ranges or "::/0" in source_ranges:
                open_rules.append({
                    "name": rule.get("name"),
                    "direction": rule.get("direction"),
                    "priority": rule.get("priority"),
                    "allowed": rule.get("allowed", []),
                    "source_ranges": source_ranges,
                    "disabled": rule.get("disabled", False),
                })
        return open_rules
    except Exception as e:
        return [{"error": str(e)}]


def list_iam_service_accounts() -> list[dict[str, Any]]:
    """List project IAM bindings — who has what role on the project."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("cloudresourcemanager", "v1", credentials=credentials)
        result = service.projects().getIamPolicy(
            resource=PROJECT, body={}
        ).execute()
        bindings = []
        for b in result.get("bindings", []):
            bindings.append({
                "role": b.get("role"),
                "members": b.get("members", []),
            })
        return bindings
    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────
# Incident / Monitoring
# ─────────────────────────────────────────────

def list_active_alerts() -> list[dict[str, Any]]:
    """List active (open) Cloud Monitoring alert incidents."""
    try:
        from google.cloud import monitoring_v3
        import google.auth

        credentials, _ = google.auth.default()
        client = monitoring_v3.AlertPolicyServiceClient(credentials=credentials)
        name = f"projects/{PROJECT}"
        alerts = []
        for policy in client.list_alert_policies(name=name):
            alerts.append({
                "name": policy.name.split("/")[-1],
                "display_name": policy.display_name,
                "enabled": policy.enabled.value if hasattr(policy.enabled, 'value') else policy.enabled,
                "conditions": [c.display_name for c in policy.conditions],
            })
        return alerts
    except Exception as e:
        return [{"error": str(e)}]


def get_compute_instance_health() -> list[dict[str, Any]]:
    """
    Return instances that are NOT in RUNNING status (degraded / stopped).
    """
    try:
        instances = list_compute_instances()
        return [i for i in instances if i.get("status") != "RUNNING"]
    except Exception as e:
        return [{"error": str(e)}]


# ─────────────────────────────────────────────
# Deployment
# ─────────────────────────────────────────────

def list_cloud_run_services() -> list[dict[str, Any]]:
    """List all Cloud Run services and their latest revision status."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("run", "v1", credentials=credentials)

        # Cloud Run v1 uses regions; try common ones
        regions = ["us-central1", "us-east1", "us-west1", "europe-west1", "asia-east1"]
        services = []
        for region in regions:
            try:
                parent = f"namespaces/{PROJECT}"
                result = service.namespaces().services().list(parent=parent).execute()
                for svc in result.get("items", []):
                    meta = svc.get("metadata", {})
                    status = svc.get("status", {})
                    conditions = status.get("conditions", [])
                    ready = next(
                        (c.get("status") for c in conditions if c.get("type") == "Ready"),
                        "Unknown"
                    )
                    services.append({
                        "name": meta.get("name"),
                        "namespace": meta.get("namespace"),
                        "ready": ready,
                        "url": status.get("url"),
                        "latest_revision": status.get("latestReadyRevisionName"),
                    })
                break  # got results
            except Exception:
                continue
        return services
    except Exception as e:
        return [{"error": str(e)}]


def list_cloud_build_recent() -> list[dict[str, Any]]:
    """List recent Cloud Build builds and their statuses."""
    try:
        from googleapiclient import discovery
        import google.auth

        credentials, _ = google.auth.default()
        service = discovery.build("cloudbuild", "v1", credentials=credentials)
        result = service.projects().builds().list(
            projectId=PROJECT,
            pageSize=20,
        ).execute()
        builds = []
        for b in result.get("builds", []):
            builds.append({
                "id": b.get("id"),
                "status": b.get("status"),
                "trigger_id": b.get("buildTriggerId"),
                "start_time": b.get("startTime"),
                "finish_time": b.get("finishTime"),
                "source": b.get("source", {}).get("repoSource", {}).get("repoName", "unknown"),
            })
        return builds
    except Exception as e:
        return [{"error": str(e)}]
