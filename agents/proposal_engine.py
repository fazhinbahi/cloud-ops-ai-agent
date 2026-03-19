"""
agents/proposal_engine.py — Claude Opus generates action proposals from findings.

For each CRITICAL/HIGH finding, Claude reasons about:
  - What is the safest targeted fix?
  - Is it reversible?
  - What is the blast radius?
  - What are the rollback instructions?

Claude returns structured JSON. The engine validates and converts to Action objects.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, SUPERVISOR_MODEL, GOOGLE_CLOUD_PROJECT, MAX_PROPOSED_ACTIONS
from memory.store import Finding
from memory.actions import Action
from execution.engine import get_available_action_types


class ProposalEngine:
    """Uses Claude Opus to propose GCP remediation actions from findings."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    def propose(self, findings: list[Finding], run_id: str) -> list[Action]:
        """
        Take CRITICAL+HIGH findings and return a list of proposed Actions.
        Returns empty list if no findings or Claude returns nothing actionable.
        """
        if not findings:
            return []

        raw = self._call_claude(findings, run_id)
        return self._parse_actions(raw, run_id)

    # ── Claude call ───────────────────────────────────────────────────────────

    def _call_claude(self, findings: list[Finding], run_id: str) -> str:
        available_types = get_available_action_types()

        system_prompt = f"""You are the action planner for a GCP cloud operations system.
You receive security, cost, and reliability findings from automated agents.
Your job is to propose safe, targeted remediation actions.

STRICT RULES — follow exactly:
1. Only propose reversible or semi-reversible actions by default.
   Irreversible actions (VM deletion) may only be proposed for CRITICAL findings
   and must have reversibility="irreversible" explicitly set.
2. Prefer the most targeted change: disable a firewall rule, do not delete it.
   Remove one public member from a bucket, do not delete the bucket.
3. Set blast_radius honestly:
   "low"    = affects one resource, no downstream service impact
   "medium" = potential brief disruption to one service
   "high"   = broad impact across multiple services or users
4. Write rollback_instructions for a tired engineer at 3am.
5. Never propose the same action_type on the same resource twice.
6. Maximum {MAX_PROPOSED_ACTIONS} actions per run. Prioritise critical > high.
7. The "parameters" dict must exactly match the function signature below.

AVAILABLE ACTION TYPES AND REQUIRED PARAMETERS:
{self._format_action_types(available_types)}

Return ONLY a JSON array. No markdown. No text outside the JSON array.
If nothing is actionable, return: []
"""

        user_msg = f"""Run ID: {run_id}
GCP Project: {GOOGLE_CLOUD_PROJECT}
Timestamp: {datetime.now(timezone.utc).isoformat()}

CRITICAL and HIGH severity findings requiring remediation:

{json.dumps([f.model_dump() for f in findings], indent=2, default=str)}

Propose remediation actions. Return a JSON array where each item has:
{{
  "finding_id": "id of the finding this addresses",
  "category": "security|cost|reliability|compliance",
  "reversibility": "reversible|semi-reversible|irreversible",
  "title": "short action title (max 60 chars)",
  "description": "what this action does and why it is recommended",
  "action_type": "one of the available types listed above",
  "parameters": {{ ... exact kwargs ... }},
  "resource": "resource name",
  "region": "gcp region or zone, empty string if global",
  "blast_radius": "low|medium|high",
  "rollback_instructions": "plain English steps to undo"
}}
"""

        response = self._client.messages.create(
            model=SUPERVISOR_MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )

        return next(
            (b.text for b in response.content if b.type == "text"), "[]"
        )

    def _format_action_types(self, types: list[str]) -> str:
        """Format available action types with their required parameters for the prompt."""
        # Parameter specs for each action type
        specs = {
            "disable_firewall_rule": 'parameters: {"project": "<project_id>", "rule_name": "<firewall_rule_name>"}',
            "restrict_firewall_source_range": 'parameters: {"project": "<project_id>", "rule_name": "<name>", "new_source_ranges": ["<cidr>", ...]}',
            "remove_bucket_public_access": 'parameters: {"project": "<project_id>", "bucket_name": "<name>", "member_to_remove": "allUsers|allAuthenticatedUsers", "role": "<role>"}',
            "stop_vm": 'parameters: {"project": "<project_id>", "zone": "<zone>", "instance_name": "<name>"}',
            "delete_stopped_vm": 'parameters: {"project": "<project_id>", "zone": "<zone>", "instance_name": "<name>"}  # IRREVERSIBLE',
        }
        lines = []
        for t in types:
            lines.append(f"  - {t}: {specs.get(t, 'see docs')}")
        return "\n".join(lines)

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse_actions(self, raw_text: str, run_id: str) -> list[Action]:
        """Parse Claude's JSON response into Action objects."""
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        valid_types = set(get_available_action_types())

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            return []

        actions: list[Action] = []
        for item in items[:MAX_PROPOSED_ACTIONS]:
            action_type = item.get("action_type", "")
            if action_type not in valid_types:
                continue  # drop unknown action types

            try:
                actions.append(Action(
                    run_id=run_id,
                    finding_id=item.get("finding_id", ""),
                    category=item.get("category", "security"),
                    reversibility=item.get("reversibility", "reversible"),
                    title=item.get("title", "Untitled action")[:80],
                    description=item.get("description", ""),
                    action_type=action_type,
                    parameters=item.get("parameters", {}),
                    resource=item.get("resource", ""),
                    region=item.get("region", ""),
                    project=GOOGLE_CLOUD_PROJECT,
                    blast_radius=item.get("blast_radius", "low"),
                    rollback_instructions=item.get("rollback_instructions", ""),
                ))
            except Exception:
                continue

        return actions
