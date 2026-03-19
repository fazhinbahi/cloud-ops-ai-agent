"""
execution/rollback.py — Phase 3 automated rollback engine.

When post-execution verification fails (or an action itself fails in a
way that leaves GCP in a partial state), the RollbackEngine automatically
executes the inverse operation.

Rollback map (forward → inverse):
  disable_firewall_rule          → enable_firewall_rule
  restrict_firewall_source_range → restore_firewall_source_range (uses before.sourceRanges)
  stop_vm                        → start_vm
  remove_bucket_public_access    → no automatic rollback (log a warning)
  delete_stopped_vm              → no automatic rollback (irreversible by design)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from memory.actions import Action, ActionsStore
from audit.log import AuditLogger
from memory.history import history_db

# ── Rollback map ──────────────────────────────────────────────────────────────
# Maps forward action_type → (rollback_action_type, parameter_builder_fn)
# parameter_builder_fn(original_action) → dict of kwargs for the rollback call

def _params_enable_firewall(a: Action) -> dict:
    return {"project": a.parameters.get("project", ""), "rule_name": a.parameters.get("rule_name", "")}

def _params_restore_source_range(a: Action) -> dict | None:
    original_ranges = (a.parameters.get("_before_source_ranges") or
                       a.parameters.get("original_source_ranges"))
    if not original_ranges:
        return None  # can't rollback without original value
    return {
        "project": a.parameters.get("project", ""),
        "rule_name": a.parameters.get("rule_name", ""),
        "original_source_ranges": original_ranges,
    }

def _params_start_vm(a: Action) -> dict:
    return {
        "project": a.parameters.get("project", ""),
        "zone": a.parameters.get("zone", ""),
        "instance_name": a.parameters.get("instance_name", ""),
    }

_ROLLBACK_MAP: dict[str, tuple[str, Any]] = {
    "disable_firewall_rule":          ("enable_firewall_rule",           _params_enable_firewall),
    "restrict_firewall_source_range": ("restore_firewall_source_range",  _params_restore_source_range),
    "stop_vm":                        ("start_vm",                       _params_start_vm),
}

# These cannot be automatically rolled back
_NO_AUTO_ROLLBACK = {"remove_bucket_public_access", "delete_stopped_vm"}


class RollbackEngine:
    """
    Executes the inverse operation for a previously executed action.

    Usage:
        engine = RollbackEngine(audit_logger=audit)
        result = engine.rollback(action, store=actions_store)
    """

    def __init__(self, audit_logger: AuditLogger, dry_run: bool = False):
        self._audit = audit_logger
        self._dry_run = dry_run

    def rollback(self, action: Action, store: ActionsStore) -> dict[str, Any]:
        """
        Attempt to roll back a single action.

        Returns {"success": bool, "message": str, "rollback_action_type": str | None}
        """
        if action.action_type in _NO_AUTO_ROLLBACK:
            msg = (
                f"'{action.action_type}' has no automatic rollback. "
                f"Manual steps: {action.rollback_instructions}"
            )
            self._audit.write(action, "rollback_skipped", detail=msg)
            return {"success": False, "message": msg, "rollback_action_type": None}

        if action.action_type not in _ROLLBACK_MAP:
            msg = f"No rollback mapping found for action_type '{action.action_type}'."
            self._audit.write(action, "rollback_skipped", detail=msg)
            return {"success": False, "message": msg, "rollback_action_type": None}

        rollback_type, param_builder = _ROLLBACK_MAP[action.action_type]
        params = param_builder(action)

        if params is None:
            msg = (
                f"Cannot build rollback parameters for '{action.action_type}' on "
                f"'{action.resource}' — original state not recorded."
            )
            self._audit.write(action, "rollback_skipped", detail=msg)
            return {"success": False, "message": msg, "rollback_action_type": rollback_type}

        if self._dry_run:
            msg = f"[DRY RUN] Would execute '{rollback_type}' on '{action.resource}'. No GCP changes made."
            self._audit.write(action, "rollback_dry_run", detail=msg)
            return {"success": True, "message": msg, "rollback_action_type": rollback_type}

        # Execute the rollback via the dispatch table
        from execution.engine import DISPATCH
        fn = DISPATCH.get(rollback_type)
        if fn is None:
            msg = f"Rollback action_type '{rollback_type}' not in dispatch table."
            self._audit.write(action, "rollback_failed", detail=msg)
            return {"success": False, "message": msg, "rollback_action_type": rollback_type}

        try:
            result = fn(**params)
        except Exception as e:
            result = {"success": False, "message": f"Rollback raised: {e}"}

        event = "rollback_succeeded" if result.get("success") else "rollback_failed"
        self._audit.write(action, event, detail=result.get("message", ""))
        history_db.mark_rollback_triggered(action.id)

        return {
            "success": result.get("success", False),
            "message": result.get("message", ""),
            "rollback_action_type": rollback_type,
        }

    def can_rollback(self, action_type: str) -> bool:
        """Return True if an automatic rollback exists for this action type."""
        return action_type in _ROLLBACK_MAP
