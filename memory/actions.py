"""
memory/actions.py — Action model and store for Phase 2.

An Action is born from a Finding. The lifecycle:
  proposed → approved/rejected (by human) → executing → succeeded/failed

The ActionsStore mirrors FindingsStore: in-memory with JSON persistence.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── Types ─────────────────────────────────────────────────────────────────────

ActionStatus = Literal[
    "proposed",   # Claude generated this, not yet reviewed
    "approved",   # human said yes
    "rejected",   # human said no
    "executing",  # in flight
    "succeeded",  # GCP API call completed successfully
    "failed",     # GCP API call raised an exception
    "skipped",    # human chose "skip all remaining" at the gate
]

ActionCategory = Literal["security", "cost", "reliability", "compliance"]

Reversibility = Literal["reversible", "semi-reversible", "irreversible"]

BlastRadius = Literal["low", "medium", "high"]


# ── Data model ────────────────────────────────────────────────────────────────

class Action(BaseModel):
    # Identity
    id: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    )
    run_id: str = ""
    finding_id: str = ""          # the Finding.id that triggered this

    # Classification
    category: ActionCategory = "security"
    reversibility: Reversibility = "reversible"

    # What to do
    title: str
    description: str
    action_type: str              # key into execution engine's dispatch table
    parameters: dict[str, Any] = Field(default_factory=dict)

    # Targeting
    resource: str = ""
    region: str = ""
    project: str = ""

    # Risk metadata
    blast_radius: BlastRadius = "low"
    rollback_instructions: str = ""

    # Lifecycle
    status: ActionStatus = "proposed"
    proposed_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    decided_at: str | None = None
    executed_at: str | None = None
    decided_by: str = "human"

    # Outcome
    outcome: str = ""
    dry_run: bool = False


# ── Store ─────────────────────────────────────────────────────────────────────

class ActionsStore:
    """In-memory + file-persisted store for Action objects."""

    def __init__(self, persist_dir: str = "./reports"):
        self._actions: list[Action] = []
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    # ── Write ──────────────────────────────────

    def add(self, action: Action) -> None:
        self._actions.append(action)

    def add_many(self, actions: list[Action]) -> None:
        self._actions.extend(actions)

    def update(self, action: Action) -> None:
        """Replace an existing action (matched by id) with the updated version."""
        for i, a in enumerate(self._actions):
            if a.id == action.id:
                self._actions[i] = action
                return
        self._actions.append(action)  # not found — add it

    # ── Read ───────────────────────────────────

    def all(self) -> list[Action]:
        return list(self._actions)

    def pending(self) -> list[Action]:
        """Actions waiting for human decision."""
        return [a for a in self._actions if a.status == "proposed"]

    def approved(self) -> list[Action]:
        return [a for a in self._actions if a.status == "approved"]

    def by_status(self, status: ActionStatus) -> list[Action]:
        return [a for a in self._actions if a.status == status]

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for a in self._actions:
            counts[a.status] = counts.get(a.status, 0) + 1
        return {"total": len(self._actions), "by_status": counts}

    # ── Persistence ────────────────────────────

    def flush_to_disk(self, run_id: str | None = None) -> Path:
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._persist_dir / f"actions_{run_id}.json"
        data = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.summary(),
            "actions": [a.model_dump() for a in self._actions],
        }
        path.write_text(json.dumps(data, indent=2))
        return path

    def clear(self) -> None:
        self._actions.clear()


# ── Module-level singleton ─────────────────────
actions_store = ActionsStore()
