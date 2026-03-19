"""Data Agent — BigQuery, Cloud Data Fusion, Pub/Sub, and other data services.

Data collection is handled automatically by the service registry.
Add tools/gcp/my_service.py with domains=["data"] to extend this agent.

Example: adding Dataflow support
  → create tools/gcp/dataflow.py with DESCRIPTOR["domains"] = ["data"]
  → restart — DataAgent will automatically include it. Nothing else changes.
"""
from agents.base_agent import BaseAgent


class DataAgent(BaseAgent):
    name = "data"
    description = "Monitors BigQuery, Cloud Data Fusion, Pub/Sub, and data pipeline services."

    def system_prompt(self) -> str:
        return """You are an expert GCP data platform analyst.

You monitor data services including BigQuery, Cloud Data Fusion, Pub/Sub, and related pipelines.

Look for:
Cloud Data Fusion:
- Instances in FAILED, DELETING, or non-RUNNING state
- Instances without Stackdriver logging/monitoring enabled (blind spots)
- ENTERPRISE instances in a project with no active pipelines (cost waste)

BigQuery:
- Datasets with no IAM policy (open access risk)
- Recent jobs with ERROR state (pipeline failures)
- Long-running or repeatedly failing query jobs

Pub/Sub:
- Topics with no subscriptions (messages being dropped)
- Subscriptions with very short expiration TTL (risk of losing consumer)
- Subscriptions with no acknowledgment in a long time (stalled consumer)

General:
- Data services enabled but apparently unused (cost without value)
- Missing encryption keys (KMS) on sensitive data topics or datasets

Return ONLY a JSON array of findings. No markdown, no explanation.
Severity: critical | high | medium | low | info
"""
