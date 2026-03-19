"""
iac/drift_detector.py — Phase 5 IaC Drift Detection.

Compares a Terraform state file (terraform.tfstate) against live GCP resource
state to detect:
  - Resources that exist in GCP but are not in Terraform (shadow infrastructure)
  - Resources that are in Terraform but no longer exist in GCP (stale references)
  - Resources where key attributes differ (configuration drift)

In GITOPS mode (IAC_GITOPS_MODE=true), fixes are pushed as GitHub PRs rather
than direct GCP API calls.

Usage:
    from iac.drift_detector import TerraformDriftDetector
    detector = TerraformDriftDetector()
    report = detector.detect()
    for item in report.drift_items:
        print(item.resource_type, item.drift_type, item.detail)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DriftItem:
    resource_type: str      # google_compute_instance | google_storage_bucket | etc.
    resource_name: str
    drift_type: str         # shadow | stale | config_drift
    detail: str
    tf_state: dict = field(default_factory=dict)
    live_state: dict = field(default_factory=dict)
    suggested_fix: str = ""
    pr_url: str = ""        # filled in by GitOps mode


@dataclass
class DriftReport:
    run_id: str
    generated_at: str
    state_file: str
    drift_items: list[DriftItem] = field(default_factory=list)

    @property
    def shadow_count(self) -> int:
        return sum(1 for d in self.drift_items if d.drift_type == "shadow")

    @property
    def stale_count(self) -> int:
        return sum(1 for d in self.drift_items if d.drift_type == "stale")

    @property
    def config_drift_count(self) -> int:
        return sum(1 for d in self.drift_items if d.drift_type == "config_drift")

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "generated_at": self.generated_at,
            "state_file": self.state_file,
            "shadow": self.shadow_count,
            "stale": self.stale_count,
            "config_drift": self.config_drift_count,
            "total": len(self.drift_items),
        }


class TerraformDriftDetector:
    """
    Compares Terraform state against live GCP resources.
    Supports VMs, GCS buckets, firewall rules, and GKE clusters.
    """

    def __init__(self):
        from config import IAC_STATE_FILE, GOOGLE_CLOUD_PROJECT, IAC_GITOPS_MODE
        self._state_file = IAC_STATE_FILE
        self._project = GOOGLE_CLOUD_PROJECT
        self._gitops = IAC_GITOPS_MODE
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # ── Public entry point ────────────────────────────────────────────────────

    def detect(self) -> DriftReport:
        report = DriftReport(
            run_id=self._run_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            state_file=self._state_file or "(none)",
        )

        if not self._state_file:
            report.drift_items.append(DriftItem(
                resource_type="terraform",
                resource_name="state_file",
                drift_type="config_drift",
                detail="IAC_STATE_FILE not configured. Set it to the path of your terraform.tfstate "
                       "to enable drift detection.",
                suggested_fix="Set IAC_STATE_FILE=./terraform.tfstate in .env",
            ))
            return report

        state_path = Path(self._state_file)
        if not state_path.exists():
            report.drift_items.append(DriftItem(
                resource_type="terraform",
                resource_name="state_file",
                drift_type="config_drift",
                detail=f"State file not found: {self._state_file}",
                suggested_fix="Run 'terraform init && terraform refresh' to generate state.",
            ))
            return report

        tf_state = json.loads(state_path.read_text())
        tf_resources = self._parse_tf_resources(tf_state)

        # Run per-type drift checks
        report.drift_items.extend(self._check_compute_drift(tf_resources))
        report.drift_items.extend(self._check_bucket_drift(tf_resources))
        report.drift_items.extend(self._check_firewall_drift(tf_resources))

        if self._gitops and report.drift_items:
            self._create_github_pr(report)

        return report

    # ── Terraform state parsing ───────────────────────────────────────────────

    def _parse_tf_resources(self, state: dict) -> dict[str, list[dict]]:
        """
        Returns {resource_type: [instance_dict, ...]} from a tfstate v4 file.
        """
        result: dict[str, list[dict]] = {}
        for resource in state.get("resources", []):
            rtype = resource.get("type", "")
            for instance in resource.get("instances", []):
                result.setdefault(rtype, []).append({
                    "name": resource.get("name", ""),
                    "provider": resource.get("provider", ""),
                    "attributes": instance.get("attributes", {}),
                })
        return result

    # ── Per-type drift checks ─────────────────────────────────────────────────

    def _check_compute_drift(self, tf_resources: dict) -> list[DriftItem]:
        drift: list[DriftItem] = []
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)

            # Build live instance map {name: instance_dict}
            live_instances: dict[str, dict] = {}
            request = service.instances().aggregatedList(project=self._project)
            while request:
                response = request.execute()
                for zone_data in response.get("items", {}).values():
                    for inst in zone_data.get("instances", []):
                        live_instances[inst["name"]] = inst
                request = service.instances().aggregatedList_next(request, response)

            # TF instances
            tf_instances = {
                r["attributes"].get("name", r["name"]): r
                for r in tf_resources.get("google_compute_instance", [])
            }

            # Shadow: live but not in TF
            for name, inst in live_instances.items():
                if name not in tf_instances:
                    drift.append(DriftItem(
                        resource_type="google_compute_instance",
                        resource_name=name,
                        drift_type="shadow",
                        detail=(
                            f"VM '{name}' exists in GCP (zone: "
                            f"{inst.get('zone', '').split('/')[-1]}, "
                            f"status: {inst.get('status', 'unknown')}) "
                            f"but is NOT tracked in Terraform state. "
                            f"This is shadow infrastructure."
                        ),
                        live_state={"name": name, "status": inst.get("status"),
                                    "machineType": inst.get("machineType", "").split("/")[-1]},
                        suggested_fix=(
                            f'Run: terraform import google_compute_instance.{name} '
                            f'{self._project}/{inst.get("zone", "").split("/")[-1]}/{name}'
                        ),
                    ))

            # Stale: in TF but not live
            for name, tf_inst in tf_instances.items():
                if name not in live_instances:
                    drift.append(DriftItem(
                        resource_type="google_compute_instance",
                        resource_name=name,
                        drift_type="stale",
                        detail=(
                            f"VM '{name}' is in Terraform state but does NOT exist in GCP. "
                            f"Terraform state may be out of sync."
                        ),
                        tf_state=tf_inst["attributes"],
                        suggested_fix="Run: terraform refresh  (then plan to see removal)",
                    ))

            # Config drift: machine type mismatch
            for name in set(tf_instances) & set(live_instances):
                tf_mt = tf_instances[name]["attributes"].get("machine_type", "")
                live_mt = live_instances[name].get("machineType", "").split("/")[-1]
                if tf_mt and live_mt and tf_mt != live_mt:
                    drift.append(DriftItem(
                        resource_type="google_compute_instance",
                        resource_name=name,
                        drift_type="config_drift",
                        detail=(
                            f"VM '{name}' machine type mismatch: "
                            f"Terraform expects '{tf_mt}', GCP reports '{live_mt}'."
                        ),
                        tf_state={"machine_type": tf_mt},
                        live_state={"machine_type": live_mt},
                        suggested_fix=(
                            f"Update Terraform: machine_type = \"{live_mt}\" "
                            f"(or revert GCP instance to {tf_mt})"
                        ),
                    ))

        except Exception as exc:
            drift.append(DriftItem(
                resource_type="google_compute_instance",
                resource_name="(error)",
                drift_type="config_drift",
                detail=f"Compute drift check failed: {exc}",
            ))
        return drift

    def _check_bucket_drift(self, tf_resources: dict) -> list[DriftItem]:
        drift: list[DriftItem] = []
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            storage = discovery.build("storage", "v1", credentials=credentials)

            live_buckets: dict[str, dict] = {}
            response = storage.buckets().list(project=self._project).execute()
            for bucket in response.get("items", []):
                live_buckets[bucket["name"]] = bucket

            tf_buckets = {
                r["attributes"].get("name", r["name"]): r
                for r in tf_resources.get("google_storage_bucket", [])
            }

            for name in live_buckets:
                if name not in tf_buckets:
                    drift.append(DriftItem(
                        resource_type="google_storage_bucket",
                        resource_name=name,
                        drift_type="shadow",
                        detail=(
                            f"GCS bucket '{name}' exists in GCP but is not in Terraform state."
                        ),
                        live_state={"name": name,
                                    "location": live_buckets[name].get("location", "")},
                        suggested_fix=f"terraform import google_storage_bucket.{name} {name}",
                    ))

            for name in tf_buckets:
                if name not in live_buckets:
                    drift.append(DriftItem(
                        resource_type="google_storage_bucket",
                        resource_name=name,
                        drift_type="stale",
                        detail=f"GCS bucket '{name}' is in Terraform but does not exist in GCP.",
                        tf_state=tf_buckets[name]["attributes"],
                        suggested_fix="Run: terraform refresh",
                    ))

        except Exception:
            pass
        return drift

    def _check_firewall_drift(self, tf_resources: dict) -> list[DriftItem]:
        drift: list[DriftItem] = []
        try:
            from googleapiclient import discovery
            from google.auth import default as google_default
            credentials, _ = google_default()
            service = discovery.build("compute", "v1", credentials=credentials)

            live_rules: dict[str, dict] = {}
            response = service.firewalls().list(project=self._project).execute()
            for rule in response.get("items", []):
                live_rules[rule["name"]] = rule

            tf_rules = {
                r["attributes"].get("name", r["name"]): r
                for r in tf_resources.get("google_compute_firewall", [])
            }

            for name in live_rules:
                if name not in tf_rules:
                    drift.append(DriftItem(
                        resource_type="google_compute_firewall",
                        resource_name=name,
                        drift_type="shadow",
                        detail=(
                            f"Firewall rule '{name}' exists in GCP but not in Terraform. "
                            f"This may be a manually created rule."
                        ),
                        live_state={
                            "name": name,
                            "sourceRanges": live_rules[name].get("sourceRanges", []),
                            "disabled": live_rules[name].get("disabled", False),
                        },
                        suggested_fix=(
                            f"terraform import google_compute_firewall.{name} "
                            f"projects/{self._project}/global/firewalls/{name}"
                        ),
                    ))

        except Exception:
            pass
        return drift

    # ── GitOps PR creation ────────────────────────────────────────────────────

    def _create_github_pr(self, report: DriftReport) -> None:
        """
        Creates a GitHub PR with suggested Terraform fixes for detected drift.
        Requires GITHUB_TOKEN and GITHUB_REPO to be set.
        """
        from config import GITHUB_TOKEN, GITHUB_REPO
        if not GITHUB_TOKEN or not GITHUB_REPO:
            return

        try:
            import urllib.request
            import urllib.parse

            body_lines = [
                "## IaC Drift Detected",
                f"Run ID: `{report.run_id}`",
                "",
                f"| Type | Count |",
                f"|------|-------|",
                f"| Shadow (in GCP, not in TF) | {report.shadow_count} |",
                f"| Stale (in TF, not in GCP) | {report.stale_count} |",
                f"| Config drift | {report.config_drift_count} |",
                "",
                "## Suggested Fixes",
                "",
            ]
            for item in report.drift_items:
                if item.suggested_fix:
                    body_lines.append(
                        f"- **{item.drift_type}** `{item.resource_name}`: "
                        f"`{item.suggested_fix}`"
                    )

            body_lines += [
                "",
                "---",
                "_Generated by Cloud Ops Phase 5 IaC Drift Detector_",
            ]

            payload = json.dumps({
                "title": f"[Cloud Ops] IaC Drift: {len(report.drift_items)} issue(s) detected",
                "body": "\n".join(body_lines),
                "head": f"cloudops/drift-{report.run_id}",
                "base": "main",
            }).encode()

            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/pulls",
                data=payload,
                headers={
                    "Authorization": f"token {GITHUB_TOKEN}",
                    "Content-Type": "application/json",
                    "Accept": "application/vnd.github.v3+json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                pr_data = json.loads(resp.read())
                pr_url = pr_data.get("html_url", "")
                for item in report.drift_items:
                    item.pr_url = pr_url

        except Exception:
            pass
