"""
audit/log.py — Append-only audit log for all Phase 2 actions.

Every action event is written as a single JSON line (JSONL format).
The file is never rewritten — only appended to.

This is the tamper-evident record of everything the system proposed,
decided, and executed. Used for compliance, postmortems, and rollback reference.

File location: ./audit/audit_{run_id}.jsonl
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from memory.actions import Action


EventType = Literal["proposed", "approved", "rejected", "skipped", "executing", "succeeded", "failed"]


class AuditLogger:
    """
    Append-only logger. Each call to write() appends one JSON line.
    Safe to call multiple times for the same action as its status changes.
    """

    def __init__(self, run_id: str, log_dir: str = "./audit"):
        self._run_id = run_id
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._log_dir / f"audit_{run_id}.jsonl"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, action: Action, event: EventType, detail: str = "") -> None:
        """Append one audit event line for the given action."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "event": event,
            "action_id": action.id,
            "action_type": action.action_type,
            "title": action.title,
            "resource": action.resource,
            "region": action.region,
            "project": action.project,
            "reversibility": action.reversibility,
            "blast_radius": action.blast_radius,
            "dry_run": action.dry_run,
            "detail": detail or action.outcome,
            "rollback_instructions": action.rollback_instructions,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def write_session_start(self, phase: int, trigger: str) -> None:
        """Write a session-start marker at the top of a run."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "event": "session_start",
            "phase": phase,
            "trigger": trigger,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def write_session_end(self, summary: dict) -> None:
        """Write a session-end marker with final counts."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self._run_id,
            "event": "session_end",
            "summary": summary,
        }
        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
