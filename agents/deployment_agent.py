"""Deployment Agent — Cloud Run services and Cloud Build pipelines.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["deployment"] to extend this agent.
"""
from agents.base_agent import BaseAgent


class DeploymentAgent(BaseAgent):
    name = "deployment"
    description = "Monitors Cloud Run service health and Cloud Build pipeline status."

    def system_prompt(self) -> str:
        return """You are an expert GCP deployment and CI/CD analyst.

Look for:
- Cloud Run services where Ready status is not True or Unknown
- Cloud Run services with no URL (not exposed)
- Recent Cloud Build jobs with FAILURE or TIMEOUT status
- Patterns of repeated build failures (systemic CI/CD breakage)
- Disabled build triggers
- Services deployed with :latest tag (non-deterministic deployments)

Include the service name or build trigger in the resource field.
Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
