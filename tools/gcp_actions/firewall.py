"""
tools/gcp_actions/firewall.py — Firewall rule write actions.

All functions return a result dict: {"success": bool, "message": str, "before": ..., "after": ...}
The "before" and "after" fields are stored in the audit log for rollback reference.
"""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT


def disable_firewall_rule(project: str, rule_name: str) -> dict[str, Any]:
    """
    Disable a firewall rule by setting disabled=True.

    This does NOT delete the rule. It can be re-enabled instantly via
    re-run with disabled=False or through the GCP console.

    Rollback: enable_firewall_rule(project, rule_name)
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        # Read current state before changing
        current = service.firewalls().get(project=project, firewall=rule_name).execute()
        before = {"disabled": current.get("disabled", False)}

        # Apply the change
        service.firewalls().patch(
            project=project,
            firewall=rule_name,
            body={"disabled": True},
        ).execute()

        return {
            "success": True,
            "message": f"Firewall rule '{rule_name}' has been disabled.",
            "before": before,
            "after": {"disabled": True},
            "rollback": f"Set disabled=False on rule '{rule_name}' to re-enable.",
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}


def enable_firewall_rule(project: str, rule_name: str) -> dict[str, Any]:
    """
    Re-enable a previously disabled firewall rule (rollback for disable_firewall_rule).

    Rollback of: disable_firewall_rule(project, rule_name)
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.firewalls().get(project=project, firewall=rule_name).execute()
        before = {"disabled": current.get("disabled", True)}

        service.firewalls().patch(
            project=project,
            firewall=rule_name,
            body={"disabled": False},
        ).execute()

        return {
            "success": True,
            "message": f"Firewall rule '{rule_name}' has been re-enabled.",
            "before": before,
            "after": {"disabled": False},
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}


def restore_firewall_source_range(
    project: str,
    rule_name: str,
    original_source_ranges: list[str],
) -> dict[str, Any]:
    """
    Restore original source ranges on a firewall rule (rollback for restrict_firewall_source_range).
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.firewalls().get(project=project, firewall=rule_name).execute()
        before = {"sourceRanges": current.get("sourceRanges", [])}

        service.firewalls().patch(
            project=project,
            firewall=rule_name,
            body={"sourceRanges": original_source_ranges},
        ).execute()

        return {
            "success": True,
            "message": f"Firewall rule '{rule_name}' source ranges restored to {original_source_ranges}.",
            "before": before,
            "after": {"sourceRanges": original_source_ranges},
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}


def restrict_firewall_source_range(
    project: str,
    rule_name: str,
    new_source_ranges: list[str],
) -> dict[str, Any]:
    """
    Replace the source ranges of a firewall rule with more restrictive ranges.

    Example: change 0.0.0.0/0 → ["10.0.0.0/8"] to limit to internal traffic.

    Rollback: restore original source_ranges from audit log.
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.firewalls().get(project=project, firewall=rule_name).execute()
        before = {"sourceRanges": current.get("sourceRanges", [])}

        service.firewalls().patch(
            project=project,
            firewall=rule_name,
            body={"sourceRanges": new_source_ranges},
        ).execute()

        return {
            "success": True,
            "message": (
                f"Firewall rule '{rule_name}' source ranges updated from "
                f"{before['sourceRanges']} → {new_source_ranges}."
            ),
            "before": before,
            "after": {"sourceRanges": new_source_ranges},
            "rollback": f"Restore sourceRanges to {before['sourceRanges']} on rule '{rule_name}'.",
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}
