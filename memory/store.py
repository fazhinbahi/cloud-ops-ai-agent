"""
memory/store.py — Shared in-memory + file-persisted findings store.

All agents write their observations here.
The Supervisor reads from here to compile the overall report.

Phase 1: Simple JSON file on disk (no vector DB yet).
Phase 2+: Replace with pgvector / Pinecone for semantic search.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Data model for a single finding
# ──────────────────────────────────────────────

Severity = Literal["info", "low", "medium", "high", "critical"]

AgentName = Literal["infra", "cost", "security", "incident", "deployment", "supervisor"]


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"))
    agent: AgentName
    severity: Severity
    title: str
    detail: str
    resource: str = ""          # e.g. "i-0abc1234", "arn:aws:s3:::my-bucket"
    region: str = ""
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    tags: dict = Field(default_factory=dict)


# ──────────────────────────────────────────────
# In-process store (singleton)
# ──────────────────────────────────────────────

class FindingsStore:
    """
    Thread-safe (enough for asyncio) findings store.
    Keeps findings in memory and optionally flushes to disk.
    """

    def __init__(self, persist_dir: str = "./reports"):
        self._findings: list[Finding] = []
        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    # ── Write ──────────────────────────────────

    def add(self, finding: Finding) -> None:
        self._findings.append(finding)

    def add_many(self, findings: list[Finding]) -> None:
        self._findings.extend(findings)

    # ── Read ───────────────────────────────────

    def all(self) -> list[Finding]:
        return list(self._findings)

    def by_agent(self, agent: AgentName) -> list[Finding]:
        return [f for f in self._findings if f.agent == agent]

    def by_severity(self, severity: Severity) -> list[Finding]:
        return [f for f in self._findings if f.severity == severity]

    def critical_and_high(self) -> list[Finding]:
        return [f for f in self._findings if f.severity in ("critical", "high")]

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for f in self._findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return {
            "total": len(self._findings),
            "by_severity": counts,
            "by_agent": {
                agent: len(self.by_agent(agent))  # type: ignore[arg-type]
                for agent in ("infra", "cost", "security", "incident", "deployment")
            },
        }

    # ── Persistence ────────────────────────────

    def flush_to_disk(self, run_id: str | None = None) -> Path:
        """Write all findings to a JSON file. Returns the path."""
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._persist_dir / f"findings_{run_id}.json"
        data = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": self.summary(),
            "findings": [f.model_dump() for f in self._findings],
        }
        path.write_text(json.dumps(data, indent=2))
        return path

    def clear(self) -> None:
        self._findings.clear()


# ── Module-level singleton ─────────────────────
store = FindingsStore()
