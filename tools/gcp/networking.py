"""GCP Networking — VPC networks and firewall rules (read-only)."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_vpc_networks() -> list[dict[str, Any]]:
    """List VPC networks and their subnets."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        result = service.networks().list(project=PROJECT).execute()
        return [{
            "name": net.get("name"),
            "auto_create_subnetworks": net.get("autoCreateSubnetworks"),
            "subnetworks": [s.split("/")[-1] for s in net.get("subnetworks", [])],
            "creation_timestamp": net.get("creationTimestamp"),
        } for net in result.get("items", [])]
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


DESCRIPTOR = {
    "api": "compute.googleapis.com",
    "display_name": "VPC Networking & Firewall",
    "domains": ["infra", "security"],
    "tools": [list_vpc_networks, list_open_firewall_rules],
}
