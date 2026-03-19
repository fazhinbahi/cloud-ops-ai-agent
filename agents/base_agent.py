"""
agents/base_agent.py — Base class shared by all specialist agents.

Each agent:
  1. Discovers which GCP tools are registered for its domain (via ServiceRegistry)
  2. Calls only the tools whose APIs are enabled in the project
  3. Sends collected data to Claude for interpretation
  4. Parses Claude's response into structured Finding objects
  5. Writes findings to the shared memory store

ADDING A NEW SERVICE TO AN EXISTING AGENT
──────────────────────────────────────────
Create tools/gcp/my_service.py with DESCRIPTOR["domains"] pointing to the
relevant agent domain. The agent picks it up automatically on next run.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from config import OBSERVE_ONLY, ANTHROPIC_API_KEY
from memory.store import Finding, store


class BaseAgent:
    """
    Base class for all specialist cloud ops agents.

    Subclasses can override:
      - name: str                  (required)
      - description: str           (optional)
      - model: str                 (optional)
      - system_prompt() -> str     (optional — defaults to generic prompt)
      - collect_data() -> dict     (optional — defaults to registry-driven collection)
    """

    name: str = "base"
    description: str = ""
    model: str = "claude-sonnet-4-6"

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ── Data collection ────────────────────────────────────────────────────────

    def collect_data(self) -> dict[str, Any]:
        """
        Default: query the service registry for tools registered to this
        agent's domain, call each one, and return the combined raw data.

        Subclasses may override for custom collection logic.
        """
        from tools.registry import get_tools_for_domain

        tools = get_tools_for_domain(self.name)
        if not tools:
            return {"note": f"No enabled GCP services registered for domain '{self.name}'."}

        data: dict[str, Any] = {}
        for descriptor, tool_fn in tools:
            service_name = descriptor.get("display_name", tool_fn.__name__)
            try:
                data[f"{service_name} / {tool_fn.__name__}"] = tool_fn()
            except Exception as e:
                data[f"{service_name} / {tool_fn.__name__}"] = {"error": str(e)}
        return data

    # ── System prompt ──────────────────────────────────────────────────────────

    def system_prompt(self) -> str:
        """
        Default system prompt — lists the services being monitored.
        Subclasses override this with domain-specific instructions.
        """
        from tools.registry import get_tools_for_domain

        tools = get_tools_for_domain(self.name)
        services = sorted({d["display_name"] for d, _ in tools})
        services_str = ", ".join(services) if services else "unknown services"

        return (
            f"You are a GCP {self.name} analyst. "
            f"You are monitoring: {services_str}. "
            f"Identify risks, misconfigurations, cost waste, and reliability issues. "
            f"Be specific — include resource names, regions, and severity."
        )

    # ── Core run loop ──────────────────────────────────────────────────────────

    def run(self) -> list[Finding]:
        """
        Execute one observe cycle:
          1. Collect raw cloud data
          2. Ask Claude to analyze it
          3. Parse findings
          4. Store in shared memory
          5. Return findings list
        """
        print(f"\n[{self.name.upper()} AGENT] Starting observation...")

        raw_data = self.collect_data()
        findings = self._analyze(raw_data)
        store.add_many(findings)

        print(f"[{self.name.upper()} AGENT] Found {len(findings)} item(s).")
        return findings

    # ── Claude analysis ────────────────────────────────────────────────────────

    def _analyze(self, raw_data: dict[str, Any]) -> list[Finding]:
        """Send raw data to Claude and parse the response into Findings."""

        user_message = f"""
Below is raw data collected from the GCP environment.
Analyze it carefully and return a JSON array of findings.

RAW DATA:
{json.dumps(raw_data, indent=2, default=str)}

Return ONLY a JSON array with this exact structure (no markdown, no explanation):
[
  {{
    "severity": "critical|high|medium|low|info",
    "title": "short one-line title",
    "detail": "detailed explanation of the issue and why it matters",
    "resource": "resource id or name if applicable",
    "region": "gcp region or zone if applicable"
  }}
]

If there are no issues, return an empty array: []
"""

        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=self.system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = next(
            (b.text for b in response.content if b.type == "text"), "[]"
        )
        return self._parse_findings(raw_text)

    def _parse_findings(self, raw_text: str) -> list[Finding]:
        """Parse Claude's JSON response into Finding objects."""
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        try:
            items = json.loads(text)
        except json.JSONDecodeError:
            return [Finding(
                agent=self.name,
                severity="info",
                title=f"{self.name} agent: could not parse response",
                detail=raw_text[:500],
            )]

        findings = []
        for item in items:
            try:
                findings.append(Finding(
                    agent=self.name,
                    severity=item.get("severity", "info"),
                    title=item.get("title", "Untitled finding"),
                    detail=item.get("detail", ""),
                    resource=item.get("resource", ""),
                    region=item.get("region", ""),
                ))
            except Exception:
                pass
        return findings
