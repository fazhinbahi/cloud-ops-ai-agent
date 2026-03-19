"""
tools/gcp_actions/compute.py — Compute Engine write actions.

All functions return a result dict: {"success": bool, "message": str, "before": ..., "after": ...}
"""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT


def stop_vm(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """
    Stop a RUNNING Compute Engine instance.

    The VM is stopped gracefully. Disk, IP config, and metadata are preserved.
    Restart is instant via GCP Console or start_vm().

    Rollback: start_vm(project, zone, instance_name)
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()
        before_status = current.get("status", "UNKNOWN")

        if before_status != "RUNNING":
            return {
                "success": False,
                "message": f"Instance '{instance_name}' is not RUNNING (status: {before_status}). No action taken.",
                "before": {"status": before_status},
                "after": {"status": before_status},
            }

        service.instances().stop(
            project=project, zone=zone, instance=instance_name
        ).execute()

        return {
            "success": True,
            "message": f"Stop signal sent to instance '{instance_name}' in zone '{zone}'.",
            "before": {"status": "RUNNING"},
            "after": {"status": "STOPPING → TERMINATED"},
            "rollback": f"Start instance '{instance_name}' via GCP Console or: gcloud compute instances start {instance_name} --zone={zone}",
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}


def start_vm(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """
    Start a TERMINATED/STOPPED Compute Engine instance (rollback for stop_vm).

    Rollback of: stop_vm(project, zone, instance_name)
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()
        before_status = current.get("status", "UNKNOWN")

        if before_status == "RUNNING":
            return {
                "success": True,
                "message": f"Instance '{instance_name}' is already RUNNING.",
                "before": {"status": before_status},
                "after": {"status": before_status},
            }

        service.instances().start(
            project=project, zone=zone, instance=instance_name
        ).execute()

        return {
            "success": True,
            "message": f"Start signal sent to instance '{instance_name}' in zone '{zone}'.",
            "before": {"status": before_status},
            "after": {"status": "STAGING → RUNNING"},
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}


def delete_stopped_vm(project: str, zone: str, instance_name: str) -> dict[str, Any]:
    """
    Delete a TERMINATED Compute Engine instance.

    ⚠ IRREVERSIBLE — this permanently deletes the VM and its ephemeral disk.
    Persistent disks attached with auto-delete=False are preserved.

    Only call this when CONFIRM_DESTRUCTIVE=True has been acknowledged.
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)

        current = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()
        before_status = current.get("status", "UNKNOWN")

        if before_status not in ("TERMINATED", "STOPPED"):
            return {
                "success": False,
                "message": (
                    f"Instance '{instance_name}' is not TERMINATED (status: {before_status}). "
                    f"Only stopped/terminated VMs may be deleted this way."
                ),
                "before": {"status": before_status},
                "after": {"status": before_status},
            }

        service.instances().delete(
            project=project, zone=zone, instance=instance_name
        ).execute()

        return {
            "success": True,
            "message": f"Instance '{instance_name}' deleted from zone '{zone}'.",
            "before": {"status": before_status, "name": instance_name},
            "after": {"status": "DELETED"},
            "rollback": "No automatic rollback available. Recreate the instance from a snapshot or backup if needed.",
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}
