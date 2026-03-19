"""
memory/history.py — Phase 3 cross-run persistent history using SQLite.

Stores findings and actions across runs so the system can:
  1. Detect recurring findings (same resource + check type appearing N times)
  2. Suppress duplicate proposals ("we already fixed this 2 days ago")
  3. Report patterns to the on-call engineer in the executive summary

The DB is append-only by design — rows are never deleted, only queried.
Backed by SQLite so there are zero infrastructure dependencies.

Usage:
    from memory.history import history_db

    history_db.record_finding(finding, run_id="20260317_120000")
    history_db.record_action(action)

    count = history_db.recurrence_count("my-bucket", "public-access", days=30)
    patterns = history_db.recurring_findings(threshold=3, days=30)
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from config import HISTORY_DB, PATTERN_WINDOW_DAYS, PATTERN_RECURRENCE_THRESHOLD


_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    agent       TEXT NOT NULL,
    severity    TEXT NOT NULL,
    title       TEXT NOT NULL,
    resource    TEXT NOT NULL,
    region      TEXT NOT NULL,
    check_type  TEXT NOT NULL,   -- derived from title, used for recurrence grouping
    detail      TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS actions (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL,
    finding_id           TEXT NOT NULL,
    action_type          TEXT NOT NULL,
    category             TEXT NOT NULL,
    title                TEXT NOT NULL,
    resource             TEXT NOT NULL,
    status               TEXT NOT NULL,
    reversibility        TEXT NOT NULL,
    blast_radius         TEXT NOT NULL,
    outcome              TEXT NOT NULL,
    dry_run              INTEGER NOT NULL DEFAULT 0,
    proposed_at          TEXT NOT NULL,
    executed_at          TEXT,
    rollback_triggered   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_findings_resource   ON findings (resource);
CREATE INDEX IF NOT EXISTS idx_findings_check_type ON findings (check_type);
CREATE INDEX IF NOT EXISTS idx_findings_run_id     ON findings (run_id);
CREATE INDEX IF NOT EXISTS idx_actions_resource    ON actions  (resource);
CREATE INDEX IF NOT EXISTS idx_actions_action_type ON actions  (action_type);
"""


class HistoryDB:
    """
    Persistent cross-run store backed by SQLite.
    Thread-safe at the SQLite level (serialized writes).
    """

    def __init__(self, db_path: str | None = None):
        path = Path(db_path or HISTORY_DB)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(path)
        self._init_schema()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Write ──────────────────────────────────────────────────────────────────

    def record_finding(self, finding, run_id: str) -> None:
        """Persist a Finding object to history."""
        check_type = _derive_check_type(finding.title)
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO findings
                    (id, run_id, agent, severity, title, resource, region,
                     check_type, detail, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding.id,
                    run_id,
                    finding.agent,
                    finding.severity,
                    finding.title,
                    finding.resource,
                    finding.region,
                    check_type,
                    finding.detail[:2000],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def record_action(self, action) -> None:
        """Persist an Action object to history."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO actions
                    (id, run_id, finding_id, action_type, category, title,
                     resource, status, reversibility, blast_radius, outcome,
                     dry_run, proposed_at, executed_at, rollback_triggered)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.id,
                    action.run_id,
                    action.finding_id,
                    action.action_type,
                    action.category,
                    action.title,
                    action.resource,
                    action.status,
                    action.reversibility,
                    action.blast_radius,
                    action.outcome or "",
                    int(action.dry_run),
                    action.proposed_at,
                    action.executed_at,
                    0,
                ),
            )

    def mark_rollback_triggered(self, action_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE actions SET rollback_triggered = 1 WHERE id = ?",
                (action_id,),
            )

    # ── Read: recurrence ───────────────────────────────────────────────────────

    def recurrence_count(self, resource: str, check_type: str, days: int | None = None) -> int:
        """
        How many times has this (resource, check_type) pair appeared in the last N days?
        If days is None, uses PATTERN_WINDOW_DAYS from config.
        """
        window = days or PATTERN_WINDOW_DAYS
        since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT run_id) AS cnt
                FROM findings
                WHERE resource = ? AND check_type = ? AND recorded_at >= ?
                """,
                (resource, check_type, since),
            ).fetchone()
        return row["cnt"] if row else 0

    def recurring_findings(
        self,
        threshold: int | None = None,
        days: int | None = None,
    ) -> list[dict]:
        """
        Return findings that have recurred >= threshold times within the window.
        Groups by (resource, check_type) and returns sorted by recurrence count desc.
        """
        threshold = threshold or PATTERN_RECURRENCE_THRESHOLD
        window = days or PATTERN_WINDOW_DAYS
        since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT resource, check_type, agent,
                       COUNT(DISTINCT run_id) AS occurrences,
                       MAX(severity) AS max_severity,
                       MAX(recorded_at) AS last_seen
                FROM findings
                WHERE recorded_at >= ?
                GROUP BY resource, check_type
                HAVING occurrences >= ?
                ORDER BY occurrences DESC
                """,
                (since, threshold),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Read: action history ───────────────────────────────────────────────────

    def was_recently_fixed(self, resource: str, action_type: str, days: int = 7) -> bool:
        """
        Return True if a successful (non-dry-run) action of this type was executed
        on this resource within the last N days. Used to suppress duplicate proposals.
        """
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS cnt FROM actions
                WHERE resource = ? AND action_type = ?
                  AND status = 'succeeded' AND dry_run = 0
                  AND executed_at >= ?
                """,
                (resource, action_type, since),
            ).fetchone()
        return (row["cnt"] > 0) if row else False

    def action_history(self, resource: str, limit: int = 20) -> list[dict]:
        """Recent action history for a given resource."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM actions
                WHERE resource = ?
                ORDER BY proposed_at DESC
                LIMIT ?
                """,
                (resource, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self, days: int | None = None) -> dict:
        window = days or PATTERN_WINDOW_DAYS
        since = (datetime.now(timezone.utc) - timedelta(days=window)).isoformat()
        with self._conn() as conn:
            finding_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM findings WHERE recorded_at >= ?", (since,)
            ).fetchone()["cnt"]
            action_count = conn.execute(
                "SELECT COUNT(*) AS cnt FROM actions WHERE proposed_at >= ?", (since,)
            ).fetchone()["cnt"]
            patterns = self.recurring_findings()
        return {
            "window_days": window,
            "total_findings": finding_count,
            "total_actions": action_count,
            "recurring_patterns": len(patterns),
            "top_patterns": patterns[:5],
        }


# ── Helpers ────────────────────────────────────────────────────────────────────

def _derive_check_type(title: str) -> str:
    """
    Derive a short stable key from a finding title for recurrence grouping.
    E.g. "Public bucket: my-bucket-123" → "public_bucket"
    """
    normalized = title.lower()
    # Map common title prefixes to stable check_type keys
    _PATTERNS = [
        ("public bucket",          "public_bucket"),
        ("open firewall",          "open_firewall"),
        ("firewall rule allows",   "open_firewall"),
        ("idle vm",                "idle_vm"),
        ("idle instance",          "idle_vm"),
        ("budget alert",           "budget_alert"),
        ("over budget",            "budget_alert"),
        ("iam",                    "iam_issue"),
        ("service account",        "service_account"),
        ("alert policy",           "alert_policy"),
        ("uptime check",           "uptime_check"),
        ("build failed",           "build_failure"),
        ("high error rate",        "high_error_rate"),
        ("sql",                    "sql_issue"),
        ("certificate",            "certificate"),
    ]
    for keyword, check_type in _PATTERNS:
        if keyword in normalized:
            return check_type
    # Fallback: first 4 words snake-cased
    words = normalized.split()[:4]
    return "_".join(w.strip(":.,-") for w in words if w.strip(":.,-"))


# ── Module-level singleton ─────────────────────────────────────────────────────
history_db = HistoryDB()
