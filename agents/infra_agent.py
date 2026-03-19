"""Infrastructure Agent — Compute, GKE, Cloud SQL, VPC networks.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["infra"] to extend this agent.
"""
from agents.base_agent import BaseAgent


class InfraAgent(BaseAgent):
    name = "infra"
    description = "Monitors Compute Engine, GKE clusters, Cloud SQL, and VPC networks."

    def system_prompt(self) -> str:
        return """You are an expert GCP infrastructure analyst.

Look for:
- Compute instances that are TERMINATED or SUSPENDED (still incurring disk cost)
- GKE clusters not in RUNNING state or with auto-upgrade disabled
- Cloud SQL instances that are stopped or publicly accessible without authorized networks
- Default VPC with auto-create-subnetworks enabled (governance anti-pattern)
- Resources missing labels (env, owner, team) — untagged = untracked
- Any resource in a degraded, failed, or deleting state

Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
