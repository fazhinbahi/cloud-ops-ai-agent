"""
agents/verifier.py — Phase 3 post-execution verification.

After an action is executed, the Verifier re-runs the relevant GCP observation
tool and checks whether the finding has been resolved. This closes the
self-healing loop:

  Execute → Wait briefly → Re-observe → Resolved? → Done
                                       → Still present? → Rollback / escalate

Each action_type maps to a verification function that queries GCP and
returns VerificationResult(resolved, detail).

If the check cannot be performed (e.g. the tool isn't accessible), the
result is marked as "unverifiable" so the action is not incorrectly rolled back.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Any

from memory.actions import Action
from config import GOOGLE_CLOUD_PROJECT


@dataclass
class VerificationResult:
    resolved: bool
    detail: str
    unverifiable: bool = False   # True = we couldn't check; don't trigger rollback


# ── Verification functions per action type ────────────────────────────────────

def _verify_firewall_disabled(action: Action) -> VerificationResult:
    """Confirm that the firewall rule is now disabled."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        project = action.parameters.get("project") or GOOGLE_CLOUD_PROJECT
        rule_name = action.parameters.get("rule_name", "")
        rule = service.firewalls().get(project=project, firewall=rule_name).execute()
        disabled = rule.get("disabled", False)
        if disabled:
            return VerificationResult(resolved=True, detail=f"Rule '{rule_name}' is now disabled.")
        return VerificationResult(resolved=False, detail=f"Rule '{rule_name}' is still enabled after action.")
    except Exception as e:
        return VerificationResult(resolved=False, unverifiable=True, detail=f"Could not verify: {e}")


def _verify_firewall_source_range(action: Action) -> VerificationResult:
    """Confirm the source ranges no longer include 0.0.0.0/0."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        project = action.parameters.get("project") or GOOGLE_CLOUD_PROJECT
        rule_name = action.parameters.get("rule_name", "")
        rule = service.firewalls().get(project=project, firewall=rule_name).execute()
        ranges = rule.get("sourceRanges", [])
        if "0.0.0.0/0" not in ranges and "::/0" not in ranges:
            return VerificationResult(resolved=True, detail=f"Rule '{rule_name}' no longer has open source ranges. Current: {ranges}")
        return VerificationResult(resolved=False, detail=f"Rule '{rule_name}' still has open source range: {ranges}")
    except Exception as e:
        return VerificationResult(resolved=False, unverifiable=True, detail=f"Could not verify: {e}")


def _verify_bucket_not_public(action: Action) -> VerificationResult:
    """Confirm allUsers / allAuthenticatedUsers are no longer bound to the bucket."""
    try:
        from google.cloud import storage
        project = action.parameters.get("project") or GOOGLE_CLOUD_PROJECT
        bucket_name = action.parameters.get("bucket_name", "")
        client = storage.Client(project=project)
        policy = client.get_bucket(bucket_name).get_iam_policy(requested_policy_version=3)
        public_members = {"allUsers", "allAuthenticatedUsers"}
        for binding in policy.bindings:
            if public_members.intersection(binding.get("members", [])):
                return VerificationResult(
                    resolved=False,
                    detail=f"Bucket '{bucket_name}' still has public members in binding: {binding.get('role')}",
                )
        return VerificationResult(resolved=True, detail=f"Bucket '{bucket_name}' has no public IAM members.")
    except Exception as e:
        return VerificationResult(resolved=False, unverifiable=True, detail=f"Could not verify: {e}")


def _verify_vm_stopped(action: Action) -> VerificationResult:
    """Confirm the VM is no longer RUNNING."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("compute", "v1", credentials=credentials)
        project = action.parameters.get("project") or GOOGLE_CLOUD_PROJECT
        zone = action.parameters.get("zone", "")
        instance_name = action.parameters.get("instance_name", "")
        instance = service.instances().get(
            project=project, zone=zone, instance=instance_name
        ).execute()
        status = instance.get("status", "UNKNOWN")
        if status in ("TERMINATED", "STOPPED", "STOPPING"):
            return VerificationResult(resolved=True, detail=f"Instance '{instance_name}' status: {status}.")
        return VerificationResult(resolved=False, detail=f"Instance '{instance_name}' still in status: {status}.")
    except Exception as e:
        return VerificationResult(resolved=False, unverifiable=True, detail=f"Could not verify: {e}")


def _unverifiable(action: Action) -> VerificationResult:
    """Placeholder for action types with no automated verification."""
    return VerificationResult(
        resolved=True,
        unverifiable=True,
        detail=f"No automated verification available for '{action.action_type}'.",
    )


# ── Verification dispatch ─────────────────────────────────────────────────────

_VERIFY_DISPATCH: dict[str, Callable[[Action], VerificationResult]] = {
    "disable_firewall_rule":          _verify_firewall_disabled,
    "restrict_firewall_source_range": _verify_firewall_source_range,
    "remove_bucket_public_access":    _verify_bucket_not_public,
    "stop_vm":                        _verify_vm_stopped,
    "delete_stopped_vm":              _unverifiable,  # VM gone — nothing to check
}


# ── Verifier class ────────────────────────────────────────────────────────────

class Verifier:
    """
    Post-execution verifier.

    Waits a short settling time then re-queries GCP to confirm the fix
    was effective. Returns VerificationResult.
    """

    # GCP operations take a moment to propagate; wait before checking.
    SETTLE_SECONDS = 5

    def verify(self, action: Action, settle: bool = True) -> VerificationResult:
        """
        Verify that an executed action had the intended effect.

        Args:
            action:  The action that was executed.
            settle:  If True, wait SETTLE_SECONDS before checking (recommended
                     for live runs). Set False in tests.
        """
        if action.status not in ("succeeded", "executing"):
            # Don't verify dry-runs or failed actions
            return VerificationResult(
                resolved=False,
                unverifiable=True,
                detail=f"Action status is '{action.status}' — verification skipped.",
            )

        if action.dry_run:
            return VerificationResult(
                resolved=True,
                unverifiable=True,
                detail="Dry-run action — no GCP state to verify.",
            )

        if settle:
            time.sleep(self.SETTLE_SECONDS)

        verify_fn = _VERIFY_DISPATCH.get(action.action_type, _unverifiable)
        return verify_fn(action)
