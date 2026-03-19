"""Incident Agent — Cloud Monitoring alerts and uptime checks.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["incident"] to extend this agent.
"""
from agents.base_agent import BaseAgent


class IncidentAgent(BaseAgent):
    name = "incident"
    description = "Monitors Cloud Monitoring alert policies and uptime checks for active incidents."

    def system_prompt(self) -> str:
        return """You are an expert GCP SRE / incident analyst.

Look for:
- Zero alert policies configured (flying blind — no observability)
- Alert policies that are disabled (monitoring gaps)
- Alert policies with no notification channels (alerts fire silently)
- No uptime checks for external-facing services
- Disabled uptime checks

In the detail field: what is affected, the likely blast radius, and what an on-call engineer should check first.
Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
