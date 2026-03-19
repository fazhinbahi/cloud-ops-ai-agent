"""
tenants/manager.py — Phase 5 Multi-Tenant RBAC Manager.

Loads team definitions from tenants/config.yaml and provides:
  - scope_findings(findings, team_id) → findings visible to that team
  - scope_actions(actions, team_id) → actions that team may approve
  - get_teams_for_finding(finding) → which teams should be notified
  - get_slack_channel(team_id) → Slack channel for routing
  - get_policy_file(team_id) → per-team policy override

Usage:
    from tenants.manager import tenant_manager
    from memory.store import Finding

    # Get findings for the security team only
    filtered = tenant_manager.scope_findings(all_findings, "security")

    # Route a finding to the right Slack channels
    channels = tenant_manager.get_teams_for_finding(finding)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Team:
    id: str
    name: str
    domains: list[str]
    projects: list[str]          # empty = all projects in scope
    slack_channel: str
    policy_file: str
    severity_filter: str         # minimum severity to show
    compliance_frameworks: list[str]

    _SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]

    def can_see_severity(self, severity: str) -> bool:
        """Return True if severity >= team's minimum filter."""
        try:
            min_idx = self._SEVERITY_ORDER.index(self.severity_filter)
            sev_idx = self._SEVERITY_ORDER.index(severity)
            return sev_idx >= min_idx
        except ValueError:
            return True

    def owns_domain(self, domain: str) -> bool:
        return not self.domains or domain in self.domains

    def owns_project(self, project: str) -> bool:
        return not self.projects or project in self.projects


class TenantManager:
    """
    Loads team configuration and provides scoped views of findings/actions.
    """

    def __init__(self):
        from config import TENANTS_CONFIG_FILE
        self._config_file = TENANTS_CONFIG_FILE
        self._teams: dict[str, Team] = {}
        self._load()

    def _load(self) -> None:
        path = Path(self._config_file)
        if not path.exists():
            return
        data = yaml.safe_load(path.read_text())
        for t in (data or {}).get("teams", []):
            team = Team(
                id=t["id"],
                name=t.get("name", t["id"]),
                domains=t.get("domains", []),
                projects=t.get("projects", []),
                slack_channel=t.get("slack_channel", ""),
                policy_file=t.get("policy_file", ""),
                severity_filter=t.get("severity_filter", "info"),
                compliance_frameworks=t.get("compliance_frameworks", []),
            )
            self._teams[team.id] = team

    # ── Public API ────────────────────────────────────────────────────────────

    def get_team(self, team_id: str) -> Team | None:
        return self._teams.get(team_id)

    def all_teams(self) -> list[Team]:
        return list(self._teams.values())

    def scope_findings(self, findings: list, team_id: str) -> list:
        """
        Return only the findings that are in scope for the given team.
        Filters by domain, project, and minimum severity.
        """
        team = self._teams.get(team_id)
        if not team:
            return findings  # unknown team → no filtering

        return [
            f for f in findings
            if team.owns_domain(getattr(f, "agent", ""))
            and team.can_see_severity(getattr(f, "severity", "info"))
            and team.owns_project(getattr(f, "tags", {}).get("project", ""))
        ]

    def scope_actions(self, actions: list, team_id: str) -> list:
        """
        Return only the actions that the given team may review/approve.
        Filtered by domain and project.
        """
        team = self._teams.get(team_id)
        if not team:
            return actions

        return [
            a for a in actions
            if team.owns_domain(getattr(a, "category", ""))
            and team.owns_project(getattr(a, "project", ""))
        ]

    def get_teams_for_finding(self, finding) -> list[Team]:
        """Return all teams that should be notified about this finding."""
        return [
            t for t in self._teams.values()
            if t.owns_domain(getattr(finding, "agent", ""))
            and t.can_see_severity(getattr(finding, "severity", "info"))
        ]

    def get_slack_channel(self, team_id: str) -> str:
        team = self._teams.get(team_id)
        return team.slack_channel if team else ""

    def get_policy_file(self, team_id: str) -> str:
        """Return the team's custom policy file, or the default if not set."""
        from config import POLICY_FILE
        team = self._teams.get(team_id)
        if team and team.policy_file:
            return team.policy_file
        return POLICY_FILE

    def route_findings_by_team(self, findings: list) -> dict[str, list]:
        """
        Returns {team_id: [findings_for_that_team], ...}
        A finding can appear in multiple team buckets.
        """
        result: dict[str, list] = {}
        for team in self._teams.values():
            scoped = self.scope_findings(findings, team.id)
            if scoped:
                result[team.id] = scoped
        return result

    def summary(self) -> dict:
        return {
            "teams": len(self._teams),
            "team_ids": list(self._teams.keys()),
            "config_file": self._config_file,
        }


# Module-level singleton
tenant_manager = TenantManager()
