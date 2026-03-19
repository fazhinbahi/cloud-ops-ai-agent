"""
slo/manager.py — Phase 5 SLO Manager.

Tracks error budgets and burn rates for services defined in slo/definitions.yaml.

Error budget = (1 - target) * window_seconds
  e.g. for 99.9% availability over 30 days:
       budget = 0.001 * 30 * 86400 = 2592 seconds of allowed downtime

Burn rate = actual error rate / (1 - target)
  if burn rate > 1.0: budget is being consumed faster than allowed
  if burn rate > alert_threshold: fire an alert

Usage:
    from slo.manager import SLOManager
    manager = SLOManager()
    results = manager.evaluate_all()
    for r in results:
        print(r.slo_id, r.burn_rate, r.budget_remaining_pct)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SLOResult:
    slo_id: str
    name: str
    service: str
    target: float
    window_days: int
    current_error_rate: float        # fraction of requests/time that are errors
    burn_rate: float                 # current_error_rate / (1 - target)
    budget_remaining_pct: float      # % of error budget remaining
    budget_remaining_minutes: float  # minutes of budget remaining
    alert: bool                      # True if burn_rate > alert_threshold
    detail: str
    severity: str = "info"           # info | medium | high | critical
    data_available: bool = True

    def to_finding_dict(self) -> dict:
        return {
            "agent": "incident",
            "severity": self.severity,
            "title": f"SLO at risk: {self.name} (burn rate {self.burn_rate:.1f}x)",
            "detail": self.detail,
            "resource": self.service,
            "region": "",
            "tags": {
                "slo_id": self.slo_id,
                "burn_rate": str(round(self.burn_rate, 3)),
                "budget_remaining_pct": str(round(self.budget_remaining_pct, 1)),
            },
        }


class SLOManager:
    """
    Evaluates all SLOs defined in slo/definitions.yaml against live Cloud Monitoring data.
    """

    def __init__(self):
        from config import SLO_DEFINITIONS_FILE, SLO_BURN_RATE_ALERT_THRESHOLD, GOOGLE_CLOUD_PROJECT
        self._definitions_file = SLO_DEFINITIONS_FILE
        self._default_threshold = SLO_BURN_RATE_ALERT_THRESHOLD
        self._project = GOOGLE_CLOUD_PROJECT

    # ── Public entry point ────────────────────────────────────────────────────

    def evaluate_all(self, inject_findings: bool = True) -> list[SLOResult]:
        slos = self._load_definitions()
        results = [self._evaluate_one(slo) for slo in slos]

        if inject_findings:
            self._inject_findings(results)

        return results

    # ── Definition loading ────────────────────────────────────────────────────

    def _load_definitions(self) -> list[dict]:
        path = Path(self._definitions_file)
        if not path.exists():
            return []
        data = yaml.safe_load(path.read_text())
        return data.get("slos", []) if data else []

    # ── Per-SLO evaluation ────────────────────────────────────────────────────

    def _evaluate_one(self, slo: dict) -> SLOResult:
        slo_id = slo.get("id", "unknown")
        name = slo.get("name", slo_id)
        service = slo.get("service", "")
        target = float(slo.get("target", 0.999))
        window_days = int(slo.get("window_days", 30))
        service_type = slo.get("service_type", "custom")
        threshold = float(slo.get("alert_burn_rate_threshold", self._default_threshold))
        region = slo.get("region", "")

        try:
            if service_type == "cloud_run":
                error_rate = self._get_cloud_run_error_rate(service, region, window_days)
            elif service_type == "uptime_check":
                error_rate = self._get_uptime_check_error_rate(service, window_days)
            elif service_type == "gke":
                error_rate = self._get_gke_error_rate(service, region, window_days)
            else:
                error_rate = self._get_custom_metric_error_rate(
                    slo.get("metric", ""), service, window_days
                )
        except Exception as exc:
            return SLOResult(
                slo_id=slo_id, name=name, service=service,
                target=target, window_days=window_days,
                current_error_rate=0.0, burn_rate=0.0,
                budget_remaining_pct=100.0, budget_remaining_minutes=0.0,
                alert=False,
                detail=f"Could not retrieve metrics: {exc}",
                data_available=False,
            )

        # Compute error budget
        allowed_error_fraction = 1.0 - target
        burn_rate = (error_rate / allowed_error_fraction) if allowed_error_fraction > 0 else 0.0

        total_budget_minutes = allowed_error_fraction * window_days * 24 * 60
        consumed_minutes = error_rate * window_days * 24 * 60
        remaining_minutes = max(0.0, total_budget_minutes - consumed_minutes)
        remaining_pct = (remaining_minutes / total_budget_minutes * 100) if total_budget_minutes > 0 else 100.0

        alert = burn_rate > threshold
        if burn_rate > threshold * 2:
            severity = "critical"
        elif burn_rate > threshold:
            severity = "high"
        elif burn_rate > 1.0:
            severity = "medium"
        else:
            severity = "info"

        detail = (
            f"SLO: {name}. Target: {target:.1%}. "
            f"Current error rate: {error_rate:.4%}. "
            f"Burn rate: {burn_rate:.2f}x (threshold: {threshold}x). "
            f"Budget remaining: {remaining_pct:.1f}% ({remaining_minutes:.0f} min over {window_days} days)."
        )
        if alert:
            detail += (
                f" ⚠ ALERT: burn rate exceeds {threshold}x — "
                f"error budget will be exhausted before month end if this continues."
            )

        return SLOResult(
            slo_id=slo_id, name=name, service=service,
            target=target, window_days=window_days,
            current_error_rate=error_rate, burn_rate=burn_rate,
            budget_remaining_pct=remaining_pct,
            budget_remaining_minutes=remaining_minutes,
            alert=alert, detail=detail, severity=severity,
        )

    # ── Metric collection ─────────────────────────────────────────────────────

    def _get_cloud_run_error_rate(
        self, service: str, region: str, window_days: int
    ) -> float:
        from google.cloud import monitoring_v3
        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{self._project}"
        now = datetime.now(timezone.utc)

        interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(now.timestamp())},
            start_time={"seconds": int((now - timedelta(days=window_days)).timestamp())},
        )
        window_seconds = window_days * 86400
        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": window_seconds},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_RATE,
        )

        # Request count
        total = self._sum_metric(
            client, project_name,
            'metric.type="run.googleapis.com/request_count" '
            f'resource.labels.service_name="{service}"',
            interval, aggregation,
        )
        # Error count (5xx)
        errors = self._sum_metric(
            client, project_name,
            'metric.type="run.googleapis.com/request_count" '
            f'resource.labels.service_name="{service}" '
            'metric.labels.response_code_class="5xx"',
            interval, aggregation,
        )
        return (errors / total) if total > 0 else 0.0

    def _get_uptime_check_error_rate(self, check_id: str, window_days: int) -> float:
        from google.cloud import monitoring_v3
        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{self._project}"
        now = datetime.now(timezone.utc)

        interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(now.timestamp())},
            start_time={"seconds": int((now - timedelta(days=window_days)).timestamp())},
        )
        window_seconds = window_days * 86400
        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": window_seconds},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_FRACTION_TRUE,
        )

        # uptime_check/check_passed: fraction of checks that passed
        passed = self._avg_metric(
            client, project_name,
            f'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
            f'metric.labels.check_id="{check_id}"',
            interval, aggregation,
        )
        return max(0.0, 1.0 - passed)

    def _get_gke_error_rate(
        self, cluster: str, region: str, window_days: int
    ) -> float:
        # Use node ready fraction as a proxy for GKE availability
        from google.cloud import monitoring_v3
        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{self._project}"
        now = datetime.now(timezone.utc)

        interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(now.timestamp())},
            start_time={"seconds": int((now - timedelta(days=window_days)).timestamp())},
        )
        window_seconds = window_days * 86400
        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": window_seconds},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_FRACTION_TRUE,
        )

        ready = self._avg_metric(
            client, project_name,
            f'metric.type="kubernetes.io/node/ready_pods_count" '
            f'resource.labels.cluster_name="{cluster}"',
            interval, aggregation,
        )
        # Fallback: no data = assume healthy
        return max(0.0, 1.0 - ready) if ready > 0 else 0.0

    def _get_custom_metric_error_rate(
        self, metric: str, resource: str, window_days: int
    ) -> float:
        return 0.0  # custom metrics require user-specified logic

    # ── Metric helpers ────────────────────────────────────────────────────────

    def _sum_metric(self, client, project, filter_str, interval, aggregation) -> float:
        total = 0.0
        for ts in client.list_time_series(
            name=project, filter=filter_str,
            interval=interval, aggregation=aggregation,
            view=1,  # FULL
        ):
            for pt in ts.points:
                total += pt.value.double_value or pt.value.int64_value
        return total

    def _avg_metric(self, client, project, filter_str, interval, aggregation) -> float:
        values = []
        for ts in client.list_time_series(
            name=project, filter=filter_str,
            interval=interval, aggregation=aggregation,
            view=1,
        ):
            for pt in ts.points:
                values.append(pt.value.double_value)
        return sum(values) / len(values) if values else 0.0

    # ── Finding injection ─────────────────────────────────────────────────────

    def _inject_findings(self, results: list[SLOResult]) -> None:
        from memory.store import store, Finding
        for r in results:
            if r.alert and r.data_available:
                fd = r.to_finding_dict()
                store.add(Finding(
                    agent="incident",
                    severity=r.severity,
                    title=fd["title"],
                    detail=r.detail,
                    resource=r.service,
                    tags=fd["tags"],
                ))
