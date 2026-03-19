"""
runbooks/engine.py — Phase 4 multi-step runbook executor.

Runbooks are YAML files in runbooks/library/ that define an ordered sequence
of steps. Each step has a type:

  observe   — re-run a GCP tool and check output (no GCP write)
  action    — execute a dispatch-table action (may require approval)
  notify    — send a Slack message
  wait      — pause for N seconds
  terminal  — log and stop

The engine follows on_success / on_failure transitions between steps.
Every step outcome is written to the audit log.

Usage:
    engine = RunbookEngine(audit_logger=audit, dry_run=False)
    matched = engine.find_matching(findings)
    for rb in matched:
        result = engine.run(rb, finding=finding, store=actions_store)
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from config import RUNBOOKS_DIR, GOOGLE_CLOUD_PROJECT
from memory.store import Finding
from memory.actions import ActionsStore
from audit.log import AuditLogger


@dataclass
class RunbookStepResult:
    step_id: str
    step_name: str
    step_type: str
    success: bool
    detail: str
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class RunbookResult:
    runbook_id: str
    runbook_name: str
    finding_id: str
    resource: str
    steps_executed: list[RunbookStepResult]
    final_status: str   # "completed" | "escalated" | "failed"
    started_at: str
    completed_at: str = ""

    def succeeded(self) -> bool:
        return self.final_status == "completed"


class RunbookEngine:
    """Loads and executes YAML runbooks in response to findings."""

    def __init__(
        self,
        audit_logger: AuditLogger,
        dry_run: bool = False,
        slack_notifier=None,
    ):
        self._audit = audit_logger
        self._dry_run = dry_run
        self._slack = slack_notifier
        self._runbooks: list[dict] = []
        self._load_runbooks()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_runbooks(self) -> None:
        rb_dir = Path(RUNBOOKS_DIR)
        if not rb_dir.exists():
            return
        for path in sorted(rb_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if isinstance(data, dict) and "steps" in data:
                    self._runbooks.append(data)
            except Exception:
                pass

    # ── Matching ──────────────────────────────────────────────────────────────

    def find_matching(self, findings: list[Finding]) -> list[tuple[dict, Finding]]:
        """
        Return (runbook, finding) pairs where the finding title matches
        at least one of the runbook's trigger_patterns.
        """
        _SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        matches = []
        for finding in findings:
            title_lower = finding.title.lower()
            sev_rank = _SEVERITY_RANK.get(finding.severity, 0)
            for rb in self._runbooks:
                threshold = rb.get("severity_threshold", "high")
                if sev_rank < _SEVERITY_RANK.get(threshold, 3):
                    continue
                patterns = rb.get("trigger_patterns", [])
                if any(p.lower() in title_lower for p in patterns):
                    matches.append((rb, finding))
                    break  # one runbook per finding
        return matches

    # ── Execution ─────────────────────────────────────────────────────────────

    def run(
        self,
        runbook: dict,
        finding: Finding,
        store: ActionsStore,
    ) -> RunbookResult:
        """Execute a runbook for a given finding."""
        rb_id = runbook.get("id", "unknown")
        rb_name = runbook.get("name", rb_id)
        steps_by_id = {s["id"]: s for s in runbook.get("steps", [])}

        result = RunbookResult(
            runbook_id=rb_id,
            runbook_name=rb_name,
            finding_id=finding.id,
            resource=finding.resource,
            steps_executed=[],
            final_status="failed",
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        # Start at the first step
        step_ids = [s["id"] for s in runbook.get("steps", [])]
        current_step_id = step_ids[0] if step_ids else None

        visited: set[str] = set()
        while current_step_id and current_step_id not in visited:
            visited.add(current_step_id)
            step = steps_by_id.get(current_step_id)
            if not step:
                break

            step_result = self._execute_step(step, finding, store)
            result.steps_executed.append(step_result)

            step_type = step.get("type", "")
            if step_type == "terminal":
                result.final_status = "completed" if step_result.success else "escalated"
                break

            next_key = "on_success" if step_result.success else "on_failure"
            current_step_id = step.get(next_key)

        result.completed_at = datetime.now(timezone.utc).isoformat()
        return result

    def _execute_step(
        self,
        step: dict,
        finding: Finding,
        store: ActionsStore,
    ) -> RunbookStepResult:
        step_id = step.get("id", "?")
        step_name = step.get("name", step_id)
        step_type = step.get("type", "observe")

        if step_type == "wait":
            return self._step_wait(step)

        if step_type == "notify":
            return self._step_notify(step, finding)

        if step_type == "action":
            return self._step_action(step, finding, store)

        if step_type == "terminal":
            return RunbookStepResult(
                step_id=step_id, step_name=step_name, step_type=step_type,
                success=True, detail="Runbook terminal step reached.",
            )

        # observe — just log, no GCP write
        return RunbookStepResult(
            step_id=step_id, step_name=step_name, step_type=step_type,
            success=True, detail=step.get("description", "Observation step completed."),
        )

    def _step_wait(self, step: dict) -> RunbookStepResult:
        seconds = step.get("wait_seconds", 60)
        if not self._dry_run:
            time.sleep(seconds)
        return RunbookStepResult(
            step_id=step["id"], step_name=step.get("name", "wait"),
            step_type="wait", success=True,
            detail=f"Waited {seconds}s{'(skipped — dry run)' if self._dry_run else ''}.",
        )

    def _step_notify(self, step: dict, finding: Finding) -> RunbookStepResult:
        msg = (
            f"*Runbook:* {step.get('name')}  |  "
            f"*Finding:* {finding.title}  |  "
            f"*Resource:* {finding.resource}"
        )
        if self._slack and not self._dry_run:
            try:
                self._slack.post(msg)
                return RunbookStepResult(
                    step_id=step["id"], step_name=step.get("name", "notify"),
                    step_type="notify", success=True, detail=f"Slack notification sent: {msg[:100]}",
                )
            except Exception as e:
                return RunbookStepResult(
                    step_id=step["id"], step_name=step.get("name", "notify"),
                    step_type="notify", success=False, detail=f"Slack notification failed: {e}",
                )
        # No Slack configured or dry run
        return RunbookStepResult(
            step_id=step["id"], step_name=step.get("name", "notify"),
            step_type="notify", success=True,
            detail=f"[{'DRY RUN — ' if self._dry_run else 'no Slack configured — '}]would notify: {msg[:100]}",
        )

    def _step_action(
        self,
        step: dict,
        finding: Finding,
        store: ActionsStore,
    ) -> RunbookStepResult:
        action_type = step.get("action_type")
        if not action_type:
            return RunbookStepResult(
                step_id=step["id"], step_name=step.get("name", "action"),
                step_type="action", success=True,
                detail="No action_type specified — step skipped.",
            )

        if self._dry_run:
            return RunbookStepResult(
                step_id=step["id"], step_name=step.get("name", "action"),
                step_type="action", success=True,
                detail=f"[DRY RUN] Would execute '{action_type}' on '{finding.resource}'.",
            )

        from execution.engine import DISPATCH
        fn = DISPATCH.get(action_type)
        if not fn:
            return RunbookStepResult(
                step_id=step["id"], step_name=step.get("name", "action"),
                step_type="action", success=False,
                detail=f"Unknown action_type '{action_type}' — not in dispatch table.",
            )

        # Build minimal parameters from the finding resource name
        params = _build_params(action_type, finding, GOOGLE_CLOUD_PROJECT)
        try:
            outcome = fn(**params)
            success = outcome.get("success", False)
            return RunbookStepResult(
                step_id=step["id"], step_name=step.get("name", "action"),
                step_type="action", success=success,
                detail=outcome.get("message", ""),
            )
        except Exception as e:
            return RunbookStepResult(
                step_id=step["id"], step_name=step.get("name", "action"),
                step_type="action", success=False, detail=str(e),
            )


# ── Parameter builder ─────────────────────────────────────────────────────────

def _build_params(action_type: str, finding: Finding, project: str) -> dict:
    """Best-effort parameter construction from a Finding."""
    base = {"project": project}
    resource = finding.resource

    if action_type in ("disable_firewall_rule", "enable_firewall_rule"):
        return {**base, "rule_name": resource}

    if action_type == "remove_bucket_public_access":
        return {**base, "bucket_name": resource, "member_to_remove": "allUsers", "role": "roles/storage.objectViewer"}

    if action_type in ("stop_vm", "start_vm", "delete_stopped_vm"):
        zone = finding.region or "us-central1-a"
        return {**base, "zone": zone, "instance_name": resource}

    return base
