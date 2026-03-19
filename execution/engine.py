"""
execution/engine.py — Executes approved actions against GCP.

The DISPATCH table maps action_type strings to the actual GCP functions.
Claude only needs to know the string key + parameter dict — it never
calls Python functions directly.

Adding a new action:
  1. Write the function in tools/gcp_actions/<domain>.py
  2. Register it in DISPATCH below
  3. Add it to the proposal engine's system prompt
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory.actions import Action, ActionsStore
from audit.log import AuditLogger


# ── Dispatch table ────────────────────────────────────────────────────────────
# Maps action_type string → callable GCP action function.
# Every function must return {"success": bool, "message": str, ...}

def _build_dispatch() -> dict[str, Any]:
    from tools.gcp_actions.firewall import (
        disable_firewall_rule,
        restrict_firewall_source_range,
        enable_firewall_rule,
        restore_firewall_source_range,
    )
    from tools.gcp_actions.storage import remove_bucket_public_access
    from tools.gcp_actions.compute import stop_vm, start_vm, delete_stopped_vm

    return {
        # Forward actions
        "disable_firewall_rule":           disable_firewall_rule,
        "restrict_firewall_source_range":  restrict_firewall_source_range,
        "remove_bucket_public_access":     remove_bucket_public_access,
        "stop_vm":                         stop_vm,
        "delete_stopped_vm":               delete_stopped_vm,
        # Rollback actions (Phase 3)
        "enable_firewall_rule":            enable_firewall_rule,
        "restore_firewall_source_range":   restore_firewall_source_range,
        "start_vm":                        start_vm,
    }


DISPATCH = _build_dispatch()


def get_available_action_types() -> list[str]:
    """Return all registered action types. Used by proposal engine's system prompt."""
    return sorted(DISPATCH.keys())


# ── Execution engine ──────────────────────────────────────────────────────────

class ExecutionEngine:
    """
    Executes a list of approved actions, one at a time.

    In dry-run mode, the GCP API call is simulated:
    the function is NOT called, but the audit log entry IS written
    with dry_run=True so you get a complete pre-flight report.
    """

    def __init__(self, audit_logger: AuditLogger, dry_run: bool = False):
        self._audit = audit_logger
        self._dry_run = dry_run

    def execute(self, actions: list[Action], store: ActionsStore) -> list[Action]:
        """
        Execute all approved actions in priority order.

        Returns the same list with status updated to succeeded/failed.
        """
        results: list[Action] = []
        approved = [a for a in actions if a.status == "approved"]

        for action in approved:
            action.dry_run = self._dry_run
            action.status = "executing"
            store.update(action)
            self._audit.write(action, "executing")

            result = self._run_single(action)

            action.executed_at = datetime.now(timezone.utc).isoformat()
            action.outcome = result.get("message", "")
            action.status = "succeeded" if result.get("success") else "failed"
            store.update(action)

            event = "succeeded" if result.get("success") else "failed"
            self._audit.write(action, event, detail=result.get("message", ""))

            results.append(action)

        return results

    def _run_single(self, action: Action) -> dict[str, Any]:
        """Run one action, respecting dry-run mode."""
        if self._dry_run:
            return {
                "success": True,
                "message": f"[DRY RUN] Would execute '{action.action_type}' on '{action.resource}'. No GCP changes made.",
            }

        fn = DISPATCH.get(action.action_type)
        if fn is None:
            return {
                "success": False,
                "message": f"Unknown action_type '{action.action_type}'. Not in dispatch table.",
            }

        try:
            return fn(**action.parameters)
        except TypeError as e:
            return {
                "success": False,
                "message": f"Parameter mismatch for '{action.action_type}': {e}",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Unexpected error: {e}",
            }
