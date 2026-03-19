"""Security Agent — IAM, firewall rules, public storage.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["security"] to extend this agent.
"""
from agents.base_agent import BaseAgent


class SecurityAgent(BaseAgent):
    name = "security"
    description = "Monitors IAM bindings, firewall rules, GCS public access, and service accounts."

    def system_prompt(self) -> str:
        return """You are an expert GCP security analyst.

Look for:
- Firewall rules allowing SSH (22) or RDP (3389) from 0.0.0.0/0
- GCS buckets with allUsers or allAuthenticatedUsers IAM bindings
- IAM bindings granting primitive roles (Owner, Editor) to users or service accounts
- Over-privileged service accounts (Editor or Owner at project level)
- Project-level IAM bindings for external (non-org) identities
- Default service account used by Compute Engine instances

Name the specific resource in the "resource" field.
Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
