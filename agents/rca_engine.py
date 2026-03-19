"""
agents/rca_engine.py — Phase 5 Root Cause Analysis Engine.

When an incident is detected (finding.severity == critical or a set of
related high findings land in the same run), the RCA engine:

  1. Collects multi-signal data from all relevant agents simultaneously
  2. Pulls recent Cloud Build deploys, IAM changes from Cloud Audit Logs,
     and Cloud Monitoring metric anomalies as correlated timeline events
  3. Feeds the full signal bundle to Claude Opus with a structured
     correlation prompt
  4. Returns a RCAResult with: causal_chain, root_cause, recommended_fix,
     and a confidence score

Usage:
    from agents.rca_engine import RCAEngine
    from memory.store import Finding

    rca = RCAEngine()
    result = rca.analyse(incident_findings)
    print(result.root_cause)
    print(result.causal_chain)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

import anthropic

from config import ANTHROPIC_API_KEY, SUPERVISOR_MODEL, GOOGLE_CLOUD_PROJECT


@dataclass
class TimelineEvent:
    timestamp: str
    source: str          # monitoring | build | audit_log | finding
    event_type: str
    resource: str
    detail: str
    severity: str = "info"


@dataclass
class RCAResult:
    run_id: str
    incident_findings: list[dict]
    timeline: list[TimelineEvent]
    causal_chain: str        # narrative causal chain from Claude
    root_cause: str          # single-sentence root cause
    recommended_fix: str     # single-sentence fix
    confidence: str          # high | medium | low
    supporting_evidence: list[str] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "root_cause": self.root_cause,
            "causal_chain": self.causal_chain,
            "recommended_fix": self.recommended_fix,
            "confidence": self.confidence,
            "supporting_evidence": self.supporting_evidence,
            "timeline_events": len(self.timeline),
        }


class RCAEngine:
    """Multi-signal root cause analysis using Claude Opus."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._project = GOOGLE_CLOUD_PROJECT
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # ── Public entry point ────────────────────────────────────────────────────

    def analyse(self, findings: list) -> RCAResult | None:
        """
        Perform RCA on a list of Finding objects. Returns None if no critical
        or high findings are present (nothing to analyse).
        """
        from config import RCA_ENABLED
        if not RCA_ENABLED:
            return None

        critical_high = [f for f in findings if f.severity in ("critical", "high")]
        if not critical_high:
            return None

        timeline = self._build_timeline(critical_high)
        result = self._correlate_with_claude(critical_high, timeline)
        return result

    # ── Timeline construction ─────────────────────────────────────────────────

    def _build_timeline(self, findings: list) -> list[TimelineEvent]:
        """Collect signals from multiple sources and merge into a timeline."""
        events: list[TimelineEvent] = []

        # 1. Convert findings to timeline events
        for f in findings:
            events.append(TimelineEvent(
                timestamp=f.timestamp,
                source="finding",
                event_type=f"finding:{f.agent}",
                resource=f.resource,
                detail=f"{f.title} — {f.detail[:200]}",
                severity=f.severity,
            ))

        # 2. Recent Cloud Build deploys (last 24h)
        events.extend(self._collect_build_events())

        # 3. Recent IAM changes from Cloud Audit Logs (last 24h)
        events.extend(self._collect_audit_log_events())

        # 4. Recent Cloud Monitoring alert firings
        events.extend(self._collect_monitoring_alerts())

        # Sort chronologically
        events.sort(key=lambda e: e.timestamp)
        return events

    def _collect_build_events(self) -> list[TimelineEvent]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("cloudbuild", "v1", credentials=credentials)

            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            response = service.projects().builds().list(
                projectId=self._project,
                filter=f'create_time>"{cutoff}"',
                pageSize=20,
            ).execute()

            events = []
            for build in response.get("builds", []):
                events.append(TimelineEvent(
                    timestamp=build.get("createTime", ""),
                    source="build",
                    event_type="deploy",
                    resource=build.get("id", "unknown"),
                    detail=(
                        f"Cloud Build {build.get('status', 'UNKNOWN')} — "
                        f"trigger: {build.get('buildTriggerId', 'manual')} — "
                        f"repo: {build.get('source', {}).get('repoSource', {}).get('repoName', 'unknown')}"
                    ),
                    severity="info" if build.get("status") == "SUCCESS" else "medium",
                ))
            return events
        except Exception:
            return []

    def _collect_audit_log_events(self) -> list[TimelineEvent]:
        try:
            from google.cloud import logging as gcp_logging
            client = gcp_logging.Client(project=self._project)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            filter_str = (
                f'logName="projects/{self._project}/logs/cloudaudit.googleapis.com%2Factivity" '
                f'timestamp>="{cutoff}" '
                'protoPayload.methodName:("setIamPolicy" OR "insert" OR "delete" OR "patch")'
            )
            events = []
            for entry in client.list_entries(filter_=filter_str, max_results=30):
                payload = entry.payload if isinstance(entry.payload, dict) else {}
                events.append(TimelineEvent(
                    timestamp=entry.timestamp.isoformat() if entry.timestamp else "",
                    source="audit_log",
                    event_type=payload.get("methodName", "unknown"),
                    resource=payload.get("resourceName", "unknown"),
                    detail=(
                        f"Principal: {payload.get('authenticationInfo', {}).get('principalEmail', 'unknown')} "
                        f"performed {payload.get('methodName', 'unknown')}"
                    ),
                    severity="medium",
                ))
            return events
        except Exception:
            return []

    def _collect_monitoring_alerts(self) -> list[TimelineEvent]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("monitoring", "v3", credentials=credentials)

            cutoff_ms = int(
                (datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000
            )
            response = service.projects().alertPolicies().list(
                name=f"projects/{self._project}"
            ).execute()

            events = []
            for policy in response.get("alertPolicies", []):
                if not policy.get("enabled", False):
                    continue
                events.append(TimelineEvent(
                    timestamp=policy.get("mutationRecord", {}).get("mutateTime", ""),
                    source="monitoring",
                    event_type="alert_policy",
                    resource=policy.get("name", ""),
                    detail=f"Alert policy: {policy.get('displayName', 'unknown')}",
                    severity="info",
                ))
            return events
        except Exception:
            return []

    # ── Claude correlation ─────────────────────────────────────────────────────

    def _correlate_with_claude(
        self,
        findings: list,
        timeline: list[TimelineEvent],
    ) -> RCAResult:
        findings_json = json.dumps(
            [f.model_dump() for f in findings], indent=2, default=str
        )
        timeline_json = json.dumps(
            [
                {
                    "timestamp": e.timestamp,
                    "source": e.source,
                    "event_type": e.event_type,
                    "resource": e.resource,
                    "detail": e.detail[:300],
                    "severity": e.severity,
                }
                for e in timeline
            ],
            indent=2,
        )

        response = self._client.messages.create(
            model=SUPERVISOR_MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system="""You are a senior Site Reliability Engineer performing root cause analysis
on a cloud infrastructure incident. You have a set of findings (observations from
monitoring agents) and a timeline of correlated events (deploys, IAM changes, alerts).

Your task:
1. Identify the most likely root cause — the single earliest event that caused the cascade.
2. Build a causal chain: what happened, in what order, and why.
3. Recommend a single targeted fix.
4. Assess your confidence: high (clear causal chain), medium (probable but uncertain), low (speculative).

Respond ONLY as valid JSON with this exact structure:
{
  "root_cause": "one sentence",
  "causal_chain": "3-5 sentence narrative",
  "recommended_fix": "one sentence",
  "confidence": "high|medium|low",
  "supporting_evidence": ["evidence item 1", "evidence item 2", "evidence item 3"]
}""",
            messages=[{
                "role": "user",
                "content": f"""INCIDENT FINDINGS:
{findings_json}

CORRELATED TIMELINE ({len(timeline)} events):
{timeline_json}

Perform root cause analysis. Respond with JSON only.""",
            }],
        )

        text = next(
            (b.text for b in response.content if b.type == "text"),
            "{}",
        )

        try:
            # Strip potential markdown fences
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {
                "root_cause": "RCA parsing failed — review findings manually.",
                "causal_chain": text[:500],
                "recommended_fix": "Review audit logs and recent deploys manually.",
                "confidence": "low",
                "supporting_evidence": [],
            }

        return RCAResult(
            run_id=self._run_id,
            incident_findings=[f.model_dump() for f in findings],
            timeline=timeline,
            causal_chain=data.get("causal_chain", ""),
            root_cause=data.get("root_cause", ""),
            recommended_fix=data.get("recommended_fix", ""),
            confidence=data.get("confidence", "low"),
            supporting_evidence=data.get("supporting_evidence", []),
        )
