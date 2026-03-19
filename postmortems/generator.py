"""
postmortems/generator.py — Phase 5 Automated Post-Mortem Generator.

Reads the audit log and findings for a completed run and uses Claude Opus
to generate a structured post-mortem Markdown document.

Structure:
  1. Executive Summary
  2. Timeline (from audit log events)
  3. Root Cause (from RCAEngine result if available)
  4. What Went Well
  5. What Went Wrong
  6. Action Items to Prevent Recurrence
  7. Metrics (MTTR, blast radius, actions taken)

Output: postmortems/reports/postmortem_{run_id}.md

Usage:
    from postmortems.generator import PostMortemGenerator
    gen = PostMortemGenerator()
    path = gen.generate(run_id="20260317_120000")
    print(f"Post-mortem saved to: {path}")
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from config import ANTHROPIC_API_KEY, SUPERVISOR_MODEL, POSTMORTEMS_DIR


class PostMortemGenerator:
    """Generates structured post-mortem Markdown from a run's audit log and findings."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._output_dir = Path(POSTMORTEMS_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ── Public entry point ────────────────────────────────────────────────────

    def generate(
        self,
        run_id: str,
        rca_result=None,
        findings: list | None = None,
    ) -> Path:
        """
        Generate a post-mortem for the given run_id.

        Args:
            run_id:      The run ID (used to find audit log and findings files).
            rca_result:  Optional RCAResult from the RCA engine.
            findings:    Optional list of Finding objects (falls back to reports/ file).

        Returns:
            Path to the generated Markdown file.
        """
        audit_events = self._load_audit_log(run_id)
        findings_data = self._load_findings(run_id, findings)
        actions_data = self._load_actions(run_id)
        rca_data = rca_result.to_dict() if rca_result else None

        markdown = self._generate_with_claude(
            run_id, audit_events, findings_data, actions_data, rca_data
        )

        output_path = self._output_dir / f"postmortem_{run_id}.md"
        output_path.write_text(markdown)
        return output_path

    # ── Data loaders ──────────────────────────────────────────────────────────

    def _load_audit_log(self, run_id: str) -> list[dict]:
        audit_path = Path(f"./audit/audit_{run_id}.jsonl")
        if not audit_path.exists():
            return []
        events = []
        for line in audit_path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events

    def _load_findings(self, run_id: str, findings: list | None) -> list[dict]:
        if findings:
            return [f.model_dump() for f in findings]
        findings_path = Path(f"./reports/findings_{run_id}.json")
        if not findings_path.exists():
            return []
        data = json.loads(findings_path.read_text())
        return data.get("findings", [])

    def _load_actions(self, run_id: str) -> list[dict]:
        actions_path = Path(f"./reports/actions_{run_id}.json")
        if not actions_path.exists():
            return []
        data = json.loads(actions_path.read_text())
        return data.get("actions", [])

    # ── Claude generation ─────────────────────────────────────────────────────

    def _generate_with_claude(
        self,
        run_id: str,
        audit_events: list[dict],
        findings: list[dict],
        actions: list[dict],
        rca: dict | None,
    ) -> str:
        severity_counts: dict[str, int] = {}
        for f in findings:
            sev = f.get("severity", "info")
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        succeeded = sum(1 for a in actions if a.get("status") == "succeeded")
        failed = sum(1 for a in actions if a.get("status") == "failed")
        rolled_back = sum(1 for a in actions if a.get("status") == "rolled_back")

        # Build timeline from audit events
        timeline_lines = []
        for e in audit_events[:40]:  # cap at 40 events for prompt size
            ts = e.get("timestamp", "")[:19]
            event = e.get("event", "")
            title = e.get("action_title", e.get("detail", ""))[:80]
            timeline_lines.append(f"  {ts} — [{event}] {title}")
        timeline_str = "\n".join(timeline_lines) or "  (no audit events recorded)"

        rca_section = ""
        if rca:
            rca_section = f"""
ROOT CAUSE ANALYSIS:
  Root cause: {rca.get('root_cause', 'Not determined')}
  Causal chain: {rca.get('causal_chain', '')}
  Recommended fix: {rca.get('recommended_fix', '')}
  RCA confidence: {rca.get('confidence', 'unknown')}
  Supporting evidence: {json.dumps(rca.get('supporting_evidence', []))}
"""

        prompt = f"""You are an experienced SRE writing a post-mortem for a cloud operations incident.

RUN ID: {run_id}
DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}

FINDINGS SUMMARY:
  Total findings: {len(findings)}
  By severity: {json.dumps(severity_counts)}

ACTIONS TAKEN:
  Total proposed: {len(actions)}
  Succeeded: {succeeded}
  Failed: {failed}
  Rolled back: {rolled_back}
  Dry-run actions: {sum(1 for a in actions if a.get('dry_run'))}

TIMELINE OF EVENTS:
{timeline_str}
{rca_section}
CRITICAL/HIGH FINDINGS (up to 5):
{json.dumps([f for f in findings if f.get('severity') in ('critical', 'high')][:5], indent=2, default=str)}

Write a professional post-mortem in Markdown. Include these sections exactly:

# Post-Mortem: {run_id}

## Executive Summary
(2-3 sentences: what happened, impact, resolution status)

## Timeline
(Use the events above, formatted as a table with columns: Time | Event | Detail)

## Root Cause
(One paragraph. If RCA data is provided, use it. Otherwise, infer from findings.)

## Impact
(What was affected, severity breakdown, blast radius)

## What Went Well
(2-4 bullet points: what the automated system did correctly)

## What Went Wrong
(2-4 bullet points: what failed or could have been caught earlier)

## Action Items
(3-5 numbered action items to prevent recurrence, each with owner: Engineering | Security | Platform)

## Metrics
| Metric | Value |
|--------|-------|
(Include: MTTR estimate, findings count, actions taken, success rate, rollbacks)

---
*Generated by Cloud Ops Phase 5 — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*
"""

        response = self._client.messages.create(
            model=SUPERVISOR_MODEL,
            max_tokens=3000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )

        return next(
            (b.text for b in response.content if b.type == "text"),
            f"# Post-Mortem: {run_id}\n\nGeneration failed — review findings manually.",
        )
