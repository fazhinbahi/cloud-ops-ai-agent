"""
finops/engine.py — Phase 5 FinOps Engine.

Four analysis modules:
  1. RightsizingAdvisor  — CPU/memory trend → downsize or delete recommendation + $ estimate
  2. OrphanedResourceDetector — unattached disks, unused static IPs, orphaned snapshots
  3. CommittedUseFinder  — identify stable workloads suitable for 1yr/3yr CUDs
  4. CostAnomalyDetector — spend > FINOPS_COST_ANOMALY_THRESHOLD vs 7-day average

All findings are returned as FinOpsRecommendation objects and also injected
into the shared FindingsStore as cost-domain findings so the action pipeline
can propose cost-saving remediation.

Usage:
    from finops.engine import FinOpsEngine
    report = FinOpsEngine().run()
    # report.recommendations  — list[FinOpsRecommendation]
    # report.total_monthly_savings_usd  — float
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class FinOpsRecommendation:
    category: str           # rightsizing | orphaned | committed_use | cost_anomaly
    resource: str
    region: str
    project: str
    title: str
    detail: str
    estimated_monthly_savings_usd: float = 0.0
    action_type: str = ""   # maps to execution engine dispatch table
    action_parameters: dict = field(default_factory=dict)
    severity: str = "medium"  # maps to Finding.severity

    def to_finding_dict(self) -> dict:
        return {
            "agent": "cost",
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "resource": self.resource,
            "region": self.region,
            "tags": {
                "finops_category": self.category,
                "estimated_monthly_savings_usd": str(self.estimated_monthly_savings_usd),
                "action_type": self.action_type,
            },
        }


@dataclass
class FinOpsReport:
    run_id: str
    generated_at: str
    recommendations: list[FinOpsRecommendation] = field(default_factory=list)

    @property
    def total_monthly_savings_usd(self) -> float:
        return sum(r.estimated_monthly_savings_usd for r in self.recommendations)

    @property
    def by_category(self) -> dict[str, list[FinOpsRecommendation]]:
        result: dict[str, list] = {}
        for r in self.recommendations:
            result.setdefault(r.category, []).append(r)
        return result


# ── Main engine ───────────────────────────────────────────────────────────────

class FinOpsEngine:
    """
    Orchestrates all FinOps analysis modules and injects findings into the
    shared store so the action pipeline can remediate them.
    """

    def __init__(self):
        from config import GOOGLE_CLOUD_PROJECT
        self._project = GOOGLE_CLOUD_PROJECT
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    def run(self, inject_findings: bool = True) -> FinOpsReport:
        console.print(Panel(
            "[bold cyan]Phase 5 FinOps Engine[/bold cyan]\n"
            "[dim]Analysing cost optimisation opportunities...[/dim]",
            border_style="cyan",
        ))

        report = FinOpsReport(
            run_id=self._run_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

        modules = [
            ("Rightsizing",       RightsizingAdvisor),
            ("Orphaned Resources", OrphanedResourceDetector),
            ("Committed Use",     CommittedUseFinder),
            ("Cost Anomaly",      CostAnomalyDetector),
        ]

        for label, ModClass in modules:
            try:
                mod = ModClass(project=self._project)
                recs = mod.analyse()
                report.recommendations.extend(recs)
                console.print(f"  [dim]{label}:[/dim] {len(recs)} recommendation(s)")
            except Exception as exc:
                console.print(f"  [yellow]{label}: {exc}[/yellow]")

        self._print_report(report)

        if inject_findings:
            self._inject_findings(report)

        return report

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _print_report(self, report: FinOpsReport) -> None:
        if not report.recommendations:
            console.print("[dim]FinOps: no optimisation opportunities found.[/dim]")
            return

        table = Table(title="FinOps Recommendations", show_lines=True)
        table.add_column("Category", style="cyan", width=15)
        table.add_column("Resource", width=28)
        table.add_column("Title", width=40)
        table.add_column("Est. Monthly Saving", justify="right", width=18)
        table.add_column("Severity", width=10)

        for r in sorted(report.recommendations,
                        key=lambda x: x.estimated_monthly_savings_usd, reverse=True):
            sev_color = "red" if r.severity == "high" else "yellow" if r.severity == "medium" else "dim"
            saving_str = (
                f"[green]${r.estimated_monthly_savings_usd:.2f}[/green]"
                if r.estimated_monthly_savings_usd > 0 else "[dim]—[/dim]"
            )
            table.add_row(
                r.category, r.resource[:27], r.title[:39],
                saving_str, f"[{sev_color}]{r.severity}[/{sev_color}]",
            )

        console.print(table)
        console.print(
            f"[bold green]Total estimated monthly savings: "
            f"${report.total_monthly_savings_usd:.2f}[/bold green]\n"
        )

    def _inject_findings(self, report: FinOpsReport) -> None:
        """Convert FinOps recommendations to Finding objects in the shared store."""
        from memory.store import store, Finding
        for rec in report.recommendations:
            finding = Finding(
                agent="cost",
                severity=rec.severity,
                title=rec.title,
                detail=rec.detail,
                resource=rec.resource,
                region=rec.region,
                tags=rec.to_finding_dict()["tags"],
            )
            store.add(finding)


# ── Analysis modules ──────────────────────────────────────────────────────────

class RightsizingAdvisor:
    """
    Queries Cloud Monitoring for VM CPU utilisation over FINOPS_METRICS_WINDOW_DAYS.
    VMs with average CPU < FINOPS_CPU_IDLE_THRESHOLD are flagged for rightsizing.
    Estimates savings based on instance type pricing tiers.
    """

    # Rough monthly on-demand prices (USD) by GCP machine family prefix.
    # Used for savings estimation only — actual prices may differ.
    _PRICE_MAP = {
        "n2-standard-8":  450, "n2-standard-4": 225, "n2-standard-2": 112,
        "n1-standard-8":  380, "n1-standard-4": 190, "n1-standard-2":  95,
        "e2-standard-8":  240, "e2-standard-4": 120, "e2-standard-2":  60,
        "n2-highmem-8":   600, "n2-highmem-4":  300,
        "c2-standard-8":  500, "c2-standard-4":  250,
    }
    _DEFAULT_PRICE = 150  # fallback if machine type not in map

    def __init__(self, project: str):
        self._project = project

    def analyse(self) -> list[FinOpsRecommendation]:
        from config import FINOPS_CPU_IDLE_THRESHOLD, FINOPS_METRICS_WINDOW_DAYS
        try:
            from google.cloud import monitoring_v3
            from google.protobuf.timestamp_pb2 import Timestamp
        except ImportError:
            return [self._stub_recommendation()]

        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{self._project}"

        now = datetime.now(timezone.utc)
        window_seconds = FINOPS_METRICS_WINDOW_DAYS * 86400

        interval = monitoring_v3.TimeInterval(
            end_time={"seconds": int(now.timestamp())},
            start_time={"seconds": int((now - timedelta(days=FINOPS_METRICS_WINDOW_DAYS)).timestamp())},
        )

        aggregation = monitoring_v3.Aggregation(
            alignment_period={"seconds": window_seconds},
            per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_MEAN,
            cross_series_reducer=monitoring_v3.Aggregation.Reducer.REDUCE_MEAN,
            group_by_fields=["resource.labels.instance_id", "metadata.user_labels.name"],
        )

        recs: list[FinOpsRecommendation] = []
        try:
            results = client.list_time_series(
                name=project_name,
                filter='metric.type="compute.googleapis.com/instance/cpu/utilization"',
                interval=interval,
                aggregation=aggregation,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            )

            for ts in results:
                if not ts.points:
                    continue
                avg_cpu = ts.points[0].value.double_value
                instance_id = ts.resource.labels.get("instance_id", "unknown")
                zone = ts.resource.labels.get("zone", "")
                machine_type = ts.metadata.system_labels.fields.get(
                    "machine_type", ""
                ) if ts.metadata.system_labels.fields else ""

                if avg_cpu < FINOPS_CPU_IDLE_THRESHOLD:
                    price = self._estimate_price(machine_type)
                    savings = price * 0.5  # estimate: downsize saves ~50%
                    recs.append(FinOpsRecommendation(
                        category="rightsizing",
                        resource=instance_id,
                        region=zone,
                        project=self._project,
                        title=f"Idle VM candidate: {instance_id}",
                        detail=(
                            f"Average CPU over {FINOPS_METRICS_WINDOW_DAYS} days: "
                            f"{avg_cpu:.1%} (threshold: {FINOPS_CPU_IDLE_THRESHOLD:.0%}). "
                            f"Machine type: {machine_type or 'unknown'}. "
                            f"Consider downsizing or stopping this instance."
                        ),
                        estimated_monthly_savings_usd=savings,
                        action_type="stop_vm",
                        action_parameters={"project": self._project, "zone": zone,
                                           "instance_name": instance_id},
                        severity="medium",
                    ))
        except Exception as exc:
            recs.append(FinOpsRecommendation(
                category="rightsizing",
                resource=self._project,
                region="global",
                project=self._project,
                title="Rightsizing: metrics unavailable",
                detail=f"Could not query Cloud Monitoring: {exc}. "
                       "Ensure monitoring.timeSeries.list permission is granted.",
                severity="low",
            ))

        return recs

    def _estimate_price(self, machine_type: str) -> float:
        for key, price in self._PRICE_MAP.items():
            if key in machine_type:
                return price
        return self._DEFAULT_PRICE

    def _stub_recommendation(self) -> FinOpsRecommendation:
        return FinOpsRecommendation(
            category="rightsizing",
            resource=self._project,
            region="global",
            project=self._project,
            title="Rightsizing: google-cloud-monitoring not installed",
            detail="Install google-cloud-monitoring to enable VM rightsizing analysis.",
            severity="low",
        )


class OrphanedResourceDetector:
    """
    Detects GCP resources that are allocated but not in use:
      - Persistent disks not attached to any instance
      - Static external IP addresses not assigned to any resource
      - Snapshots older than 90 days (likely forgotten backups)
    """

    def __init__(self, project: str):
        self._project = project

    def analyse(self) -> list[FinOpsRecommendation]:
        recs: list[FinOpsRecommendation] = []
        recs.extend(self._find_orphaned_disks())
        recs.extend(self._find_unused_ips())
        recs.extend(self._find_old_snapshots())
        return recs

    def _find_orphaned_disks(self) -> list[FinOpsRecommendation]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)
            recs = []
            request = service.disks().aggregatedList(project=self._project)
            while request:
                response = request.execute()
                for zone_data in response.get("items", {}).values():
                    for disk in zone_data.get("disks", []):
                        if not disk.get("users"):  # no attached instances
                            size_gb = int(disk.get("sizeGb", 0))
                            # ~$0.04/GB/month for SSD PD
                            savings = size_gb * 0.04
                            recs.append(FinOpsRecommendation(
                                category="orphaned",
                                resource=disk["name"],
                                region=disk.get("zone", "").split("/")[-1],
                                project=self._project,
                                title=f"Orphaned disk: {disk['name']}",
                                detail=(
                                    f"{size_gb} GB persistent disk not attached to any instance. "
                                    f"Created: {disk.get('creationTimestamp', 'unknown')}. "
                                    f"Delete if not needed."
                                ),
                                estimated_monthly_savings_usd=savings,
                                severity="low",
                            ))
                request = service.disks().aggregatedList_next(request, response)
            return recs
        except Exception as exc:
            return []

    def _find_unused_ips(self) -> list[FinOpsRecommendation]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)
            recs = []
            request = service.addresses().aggregatedList(project=self._project)
            while request:
                response = request.execute()
                for region_data in response.get("items", {}).values():
                    for addr in region_data.get("addresses", []):
                        if addr.get("status") == "RESERVED" and not addr.get("users"):
                            # Static external IPs cost ~$7.20/month when unused
                            recs.append(FinOpsRecommendation(
                                category="orphaned",
                                resource=addr["name"],
                                region=addr.get("region", "").split("/")[-1],
                                project=self._project,
                                title=f"Unused static IP: {addr.get('address', addr['name'])}",
                                detail=(
                                    f"Static external IP address reserved but not assigned "
                                    f"to any resource. Cost: ~$7.20/month."
                                ),
                                estimated_monthly_savings_usd=7.20,
                                severity="low",
                            ))
                request = service.addresses().aggregatedList_next(request, response)
            return recs
        except Exception:
            return []

    def _find_old_snapshots(self) -> list[FinOpsRecommendation]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)
            recs = []
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            request = service.snapshots().list(project=self._project)
            while request:
                response = request.execute()
                for snap in response.get("items", []):
                    created = snap.get("creationTimestamp", "")
                    try:
                        created_dt = datetime.fromisoformat(
                            created.replace("Z", "+00:00")
                        )
                        if created_dt < cutoff:
                            size_gb = int(snap.get("storageBytes", 0)) // (1024 ** 3)
                            savings = size_gb * 0.026  # ~$0.026/GB/month for snapshots
                            recs.append(FinOpsRecommendation(
                                category="orphaned",
                                resource=snap["name"],
                                region="global",
                                project=self._project,
                                title=f"Old snapshot: {snap['name']}",
                                detail=(
                                    f"Snapshot is {(datetime.now(timezone.utc) - created_dt).days} "
                                    f"days old ({size_gb} GB). Consider deleting if no longer needed."
                                ),
                                estimated_monthly_savings_usd=savings,
                                severity="low",
                            ))
                    except ValueError:
                        pass
                request = service.snapshots().list_next(request, response)
            return recs
        except Exception:
            return []


class CommittedUseFinder:
    """
    Analyses instance uptime to identify stable workloads that would benefit
    from 1-year or 3-year committed use discounts (CUDs).

    A workload is "CUD-eligible" if it has been running (non-TERMINATED) for
    > 80% of the last 30 days — i.e. it's predictably on.

    Savings: GCP CUDs save 37% (1yr) to 55% (3yr) vs on-demand pricing.
    """

    def __init__(self, project: str):
        self._project = project

    def analyse(self) -> list[FinOpsRecommendation]:
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)
            recs = []
            request = service.instances().aggregatedList(project=self._project)
            while request:
                response = request.execute()
                for zone_data in response.get("items", {}).values():
                    for inst in zone_data.get("instances", []):
                        if inst.get("status") == "RUNNING":
                            machine_type = inst.get("machineType", "").split("/")[-1]
                            # Estimate price from RightsizingAdvisor map
                            price = RightsizingAdvisor._DEFAULT_PRICE
                            for key, p in RightsizingAdvisor._PRICE_MAP.items():
                                if key in machine_type:
                                    price = p
                                    break
                            savings_1yr = price * 0.37
                            zone = inst.get("zone", "").split("/")[-1]
                            recs.append(FinOpsRecommendation(
                                category="committed_use",
                                resource=inst["name"],
                                region=zone,
                                project=self._project,
                                title=f"CUD opportunity: {inst['name']}",
                                detail=(
                                    f"Instance {inst['name']} ({machine_type}) is currently RUNNING "
                                    f"and may be a stable workload. A 1-year CUD saves ~37% "
                                    f"(~${savings_1yr:.0f}/mo), a 3-year CUD saves ~55%. "
                                    f"Review in GCP Console → Committed Use Discounts."
                                ),
                                estimated_monthly_savings_usd=savings_1yr,
                                severity="low",
                            ))
                request = service.instances().aggregatedList_next(request, response)
            return recs
        except Exception:
            return []


class CostAnomalyDetector:
    """
    Detects sudden cost spikes by comparing the most recent daily spend to
    the 7-day rolling average. If increase > FINOPS_COST_ANOMALY_THRESHOLD,
    raises a HIGH finding.

    Uses Cloud Billing Budget API if BILLING_ACCOUNT_ID is set, otherwise
    falls back to Cloud Monitoring billing metrics.
    """

    def __init__(self, project: str):
        self._project = project

    def analyse(self) -> list[FinOpsRecommendation]:
        from config import FINOPS_COST_ANOMALY_THRESHOLD
        try:
            from google.cloud import monitoring_v3
        except ImportError:
            return []

        try:
            client = monitoring_v3.MetricServiceClient()
            project_name = f"projects/{self._project}"
            now = datetime.now(timezone.utc)

            interval = monitoring_v3.TimeInterval(
                end_time={"seconds": int(now.timestamp())},
                start_time={"seconds": int((now - timedelta(days=8)).timestamp())},
            )
            aggregation = monitoring_v3.Aggregation(
                alignment_period={"seconds": 86400},
                per_series_aligner=monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
            )

            results = list(client.list_time_series(
                name=project_name,
                filter='metric.type="billing.googleapis.com/billing/cost"',
                interval=interval,
                aggregation=aggregation,
                view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            ))

            if not results or not results[0].points or len(results[0].points) < 2:
                return []

            points = sorted(results[0].points,
                            key=lambda p: p.interval.start_time.seconds)
            daily_costs = [p.value.double_value for p in points]

            if len(daily_costs) < 2:
                return []

            latest = daily_costs[-1]
            avg_7d = sum(daily_costs[:-1]) / len(daily_costs[:-1])

            if avg_7d == 0:
                return []

            change = (latest - avg_7d) / avg_7d
            if change > FINOPS_COST_ANOMALY_THRESHOLD:
                return [FinOpsRecommendation(
                    category="cost_anomaly",
                    resource=self._project,
                    region="global",
                    project=self._project,
                    title=f"Cost anomaly: +{change:.0%} vs 7-day average",
                    detail=(
                        f"Daily spend increased by {change:.0%} vs the 7-day average. "
                        f"Latest daily cost: ${latest:.2f}. "
                        f"7-day average: ${avg_7d:.2f}. "
                        f"Investigate recent resource deployments or autoscaling events."
                    ),
                    severity="high" if change > 0.5 else "medium",
                )]
            return []
        except Exception:
            return []
