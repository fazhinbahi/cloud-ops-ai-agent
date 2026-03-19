"""
agents/policy_engine.py — Phase 3 policy-based auto-approval engine.

Evaluates each proposed Action against a YAML rule set and returns one of:
  "auto_approve"  — safe to execute without human input
  "require_human" — show the Phase 2 approval gate prompt
  "auto_reject"   — silently reject, never execute

Rule evaluation: rules are checked top-to-bottom. First match wins.
If no rule matches, the configured default decision is used.

Usage:
    engine = PolicyEngine()
    decision = engine.evaluate(action)   # "auto_approve" | "require_human" | "auto_reject"
    summary  = engine.explain(action)    # human-readable reason string
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

from memory.actions import Action
from config import POLICY_FILE

Decision = Literal["auto_approve", "require_human", "auto_reject"]

_VALID_DECISIONS: set[str] = {"auto_approve", "require_human", "auto_reject"}


class PolicyRule:
    """A single parsed rule from the YAML policy file."""

    def __init__(self, data: dict):
        self.name: str = data.get("name", "unnamed")
        self.description: str = data.get("description", "")
        self.decision: Decision = data.get("decision", "require_human")  # type: ignore[assignment]
        # Condition fields — None means "match any"
        self.action_types: list[str] | None = data.get("action_types")
        self.categories: list[str] | None = data.get("categories")
        self.blast_radius: list[str] | None = data.get("blast_radius")
        self.reversibility: list[str] | None = data.get("reversibility")
        self.severities: list[str] | None = data.get("severities")

    def matches(self, action: Action) -> bool:
        """Return True if this rule applies to the given action."""
        if self.action_types and action.action_type not in self.action_types:
            return False
        if self.categories and action.category not in self.categories:
            return False
        if self.blast_radius and action.blast_radius not in self.blast_radius:
            return False
        if self.reversibility and action.reversibility not in self.reversibility:
            return False
        # severity check is intentionally loose — any match in the list is enough
        return True


class PolicyEngine:
    """
    Loads a YAML policy file and evaluates Actions against it.

    Falls back gracefully: if the policy file is missing or malformed,
    every action defaults to "require_human".
    """

    def __init__(self, policy_file: str | None = None):
        path = Path(policy_file or POLICY_FILE)
        self._rules: list[PolicyRule] = []
        self._default: Decision = "require_human"
        self._load(path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def evaluate(self, action: Action) -> Decision:
        """Return the policy decision for the given action."""
        for rule in self._rules:
            if rule.matches(action):
                return rule.decision
        return self._default

    def explain(self, action: Action) -> str:
        """Return a human-readable explanation of why the decision was made."""
        for rule in self._rules:
            if rule.matches(action):
                desc = rule.description or f"matched rule '{rule.name}'"
                return f"[{rule.decision}] {desc}"
        return f"[{self._default}] No rule matched — using default policy."

    def summary(self) -> dict:
        return {
            "policy_file": str(POLICY_FILE),
            "rules_loaded": len(self._rules),
            "default_decision": self._default,
        }

    # ── Internal ───────────────────────────────────────────────────────────────

    def _load(self, path: Path) -> None:
        if not path.exists():
            return  # no policy file → all actions go to require_human (default)
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            return  # malformed YAML → fail safe, use default

        if not isinstance(data, dict):
            return

        raw_default = data.get("default", "require_human")
        if raw_default in _VALID_DECISIONS:
            self._default = raw_default  # type: ignore[assignment]

        for rule_data in data.get("rules", []):
            if not isinstance(rule_data, dict):
                continue
            decision = rule_data.get("decision", "")
            if decision not in _VALID_DECISIONS:
                continue  # skip rules with invalid decision values
            self._rules.append(PolicyRule(rule_data))
