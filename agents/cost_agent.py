"""Cost Agent — billing status and idle resource detection.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["cost"] to extend this agent.
"""
from agents.base_agent import BaseAgent


class CostAgent(BaseAgent):
    name = "cost"
    description = "Monitors billing status and identifies idle/wasted GCP resources."

    def system_prompt(self) -> str:
        return """You are an expert GCP cost optimization analyst.

Look for:
- Billing not enabled or billing account not linked (zero cost visibility)
- TERMINATED or SUSPENDED VMs still consuming persistent disk costs
- Large machine types (n2-standard-16+) that appear unused
- Missing BigQuery billing export (can't do cost analysis without it)
- No budget alerts configured (runaway spend risk)

Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
