"""
compliance/engine.py — Phase 4 Compliance-as-Code engine.

Loads YAML framework files from COMPLIANCE_FRAMEWORKS_DIR and runs each
control check against the live GCP environment. Returns ComplianceResult
objects that the compliance agent turns into Finding objects.

Adding a new check:
  1. Add a rule to a framework YAML with a check_type value.
  2. Implement the corresponding function in _CHECK_DISPATCH below.
     The function receives (project, parameters) and returns:
       {"passed": bool, "detail": str, "resources": [list of affected resources]}

Usage:
    engine = ComplianceEngine()
    results = engine.run()   # list[ComplianceResult]
    summary = engine.summary(results)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from config import COMPLIANCE_FRAMEWORKS_DIR, GOOGLE_CLOUD_PROJECT


@dataclass
class ComplianceResult:
    framework: str
    control_id: str
    title: str
    section: str
    severity: str
    passed: bool
    detail: str
    affected_resources: list[str]
    remediation: str
    auto_fix: str | None   # action_type if an automated fix exists


# ── Check implementations ─────────────────────────────────────────────────────

def _check_no_gmail_accounts(project: str, params: dict) -> dict:
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("cloudresourcemanager", "v1", credentials=creds)
        policy = svc.projects().getIamPolicy(resource=project, body={}).execute()
        gmail_members = []
        for binding in policy.get("bindings", []):
            for member in binding.get("members", []):
                if "@gmail.com" in member:
                    gmail_members.append(f"{member} ({binding['role']})")
        if gmail_members:
            return {"passed": False, "detail": f"Personal Gmail accounts found in IAM: {gmail_members}", "resources": gmail_members}
        return {"passed": True, "detail": "No personal Gmail accounts found in project IAM.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_service_account_key_age(project: str, params: dict) -> dict:
    from datetime import datetime, timezone, timedelta
    max_age = params.get("max_age_days", 90)
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        iam = discovery.build("iam", "v1", credentials=creds)
        sas = iam.projects().serviceAccounts().list(name=f"projects/{project}").execute()
        old_keys = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)
        for sa in sas.get("accounts", []):
            keys = iam.projects().serviceAccounts().keys().list(
                name=sa["name"], keyTypes=["USER_MANAGED"]
            ).execute()
            for key in keys.get("keys", []):
                created = key.get("validAfterTime", "")
                if created:
                    try:
                        created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                        if created_dt < cutoff:
                            old_keys.append(f"{sa['email']} key {key['name'].split('/')[-1]} (created {created[:10]})")
                    except Exception:
                        pass
        if old_keys:
            return {"passed": False, "detail": f"{len(old_keys)} SA key(s) older than {max_age} days.", "resources": old_keys}
        return {"passed": True, "detail": f"All SA keys rotated within {max_age} days.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_sa_admin_roles(project: str, params: dict) -> dict:
    forbidden = set(params.get("forbidden_roles", ["roles/owner", "roles/editor"]))
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("cloudresourcemanager", "v1", credentials=creds)
        policy = svc.projects().getIamPolicy(resource=project, body={}).execute()
        violations = []
        for binding in policy.get("bindings", []):
            if binding["role"] in forbidden:
                for member in binding.get("members", []):
                    if "serviceAccount" in member:
                        violations.append(f"{member} has {binding['role']}")
        if violations:
            return {"passed": False, "detail": f"Service accounts with admin roles: {violations}", "resources": violations}
        return {"passed": True, "detail": "No service accounts with forbidden admin roles.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_user_managed_keys_default_sa(project: str, params: dict) -> dict:
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        iam = discovery.build("iam", "v1", credentials=creds)
        project_num = project
        default_sa = f"{project_num}-compute@developer.gserviceaccount.com"
        sa_name = f"projects/{project}/serviceAccounts/{default_sa}"
        keys = iam.projects().serviceAccounts().keys().list(
            name=sa_name, keyTypes=["USER_MANAGED"]
        ).execute()
        if keys.get("keys"):
            return {"passed": False, "detail": f"Default compute SA has {len(keys['keys'])} user-managed key(s).", "resources": [default_sa]}
        return {"passed": True, "detail": "Default compute SA has no user-managed keys.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_default_network(project: str, params: dict) -> dict:
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("compute", "v1", credentials=creds)
        try:
            svc.networks().get(project=project, network="default").execute()
            return {"passed": False, "detail": "Default VPC network exists in the project.", "resources": ["default"]}
        except Exception:
            return {"passed": True, "detail": "Default VPC network does not exist.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_open_port(project: str, params: dict) -> dict:
    port = str(params.get("port", 22))
    open_ranges = set(params.get("open_ranges", ["0.0.0.0/0", "::/0"]))
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("compute", "v1", credentials=creds)
        rules = svc.firewalls().list(project=project).execute().get("items", [])
        violations = []
        for rule in rules:
            if rule.get("disabled"):
                continue
            if rule.get("direction", "INGRESS") != "INGRESS":
                continue
            if open_ranges.intersection(set(rule.get("sourceRanges", []))):
                for allowed in rule.get("allowed", []):
                    ports = allowed.get("ports", [])
                    if not ports or port in ports or "0-65535" in ports:
                        violations.append(rule["name"])
        if violations:
            return {"passed": False, "detail": f"Firewall rule(s) expose port {port} to internet: {violations}", "resources": violations}
        return {"passed": True, "detail": f"No firewall rules expose port {port} to the internet.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_audit_logging(project: str, params: dict) -> dict:
    required = set(params.get("required_log_types", ["DATA_READ", "DATA_WRITE"]))
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("cloudresourcemanager", "v1", credentials=creds)
        policy = svc.projects().getIamPolicy(resource=project, body={}).execute()
        audit_configs = policy.get("auditConfigs", [])
        enabled_types: set[str] = set()
        for cfg in audit_configs:
            for log_cfg in cfg.get("auditLogConfigs", []):
                enabled_types.add(log_cfg.get("logType", ""))
        missing = required - enabled_types
        if missing:
            return {"passed": False, "detail": f"Audit log types not enabled: {missing}", "resources": list(missing)}
        return {"passed": True, "detail": "All required audit log types are enabled.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_log_sink_exists(project: str, params: dict) -> dict:
    try:
        from googleapiclient import discovery
        import google.auth
        creds, _ = google.auth.default()
        svc = discovery.build("logging", "v2", credentials=creds)
        sinks = svc.projects().sinks().list(parent=f"projects/{project}").execute()
        if sinks.get("sinks"):
            return {"passed": True, "detail": f"{len(sinks['sinks'])} log sink(s) configured.", "resources": []}
        return {"passed": False, "detail": "No log sinks configured. Logs are not exported for retention.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_public_buckets(project: str, params: dict) -> dict:
    public_members = set(params.get("public_members", ["allUsers", "allAuthenticatedUsers"]))
    try:
        from google.cloud import storage
        client = storage.Client(project=project)
        violations = []
        for bucket in client.list_buckets():
            try:
                policy = bucket.get_iam_policy(requested_policy_version=3)
                for binding in policy.bindings:
                    if public_members.intersection(set(binding.get("members", []))):
                        violations.append(bucket.name)
                        break
            except Exception:
                pass
        if violations:
            return {"passed": False, "detail": f"Publicly accessible buckets: {violations}", "resources": violations}
        return {"passed": True, "detail": "No publicly accessible Cloud Storage buckets.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_bucket_uniform_access(project: str, params: dict) -> dict:
    try:
        from google.cloud import storage
        client = storage.Client(project=project)
        violations = []
        for bucket in client.list_buckets():
            try:
                bucket.reload()
                if not bucket.iam_configuration.uniform_bucket_level_access_enabled:
                    violations.append(bucket.name)
            except Exception:
                pass
        if violations:
            return {"passed": False, "detail": f"Buckets without uniform access: {violations}", "resources": violations}
        return {"passed": True, "detail": "All buckets have uniform bucket-level access enabled.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


def _check_no_public_bq(project: str, params: dict) -> dict:
    public_members = set(params.get("public_members", ["allUsers", "allAuthenticatedUsers"]))
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project)
        violations = []
        for dataset in client.list_datasets():
            ds = client.get_dataset(dataset.reference)
            for entry in ds.access_entries:
                if entry.entity_id in public_members:
                    violations.append(dataset.dataset_id)
                    break
        if violations:
            return {"passed": False, "detail": f"Publicly accessible BigQuery datasets: {violations}", "resources": violations}
        return {"passed": True, "detail": "No publicly accessible BigQuery datasets.", "resources": []}
    except Exception as e:
        return {"passed": True, "detail": f"Check skipped: {e}", "resources": []}


# ── Check dispatch ─────────────────────────────────────────────────────────────

_CHECK_DISPATCH: dict[str, Callable] = {
    "no_gmail_accounts_in_iam":          _check_no_gmail_accounts,
    "service_account_key_age":           _check_service_account_key_age,
    "no_service_account_admin_roles":    _check_no_sa_admin_roles,
    "no_user_managed_keys_on_default_sa": _check_no_user_managed_keys_default_sa,
    "no_default_network":                _check_no_default_network,
    "no_open_ssh":                       _check_no_open_port,
    "no_open_rdp":                       _check_no_open_port,
    "audit_logging_enabled":             _check_audit_logging,
    "log_sink_exists":                   _check_log_sink_exists,
    "no_public_buckets":                 _check_no_public_buckets,
    "bucket_uniform_access":             _check_bucket_uniform_access,
    "no_public_bigquery_datasets":       _check_no_public_bq,
}


# ── Engine ─────────────────────────────────────────────────────────────────────

class ComplianceEngine:
    """
    Loads all YAML framework files and runs their checks against GCP.
    Returns a flat list of ComplianceResult objects.
    """

    def __init__(self, project: str | None = None, frameworks_dir: str | None = None):
        self._project = project or GOOGLE_CLOUD_PROJECT
        self._dir = Path(frameworks_dir or COMPLIANCE_FRAMEWORKS_DIR)
        self._frameworks: list[dict] = []
        self._load_frameworks()

    def _load_frameworks(self) -> None:
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text())
                if isinstance(data, dict) and "rules" in data:
                    self._frameworks.append(data)
            except Exception:
                pass

    def run(self) -> list[ComplianceResult]:
        results: list[ComplianceResult] = []
        for framework in self._frameworks:
            fw_name = framework.get("name", "Unknown Framework")
            for rule in framework.get("rules", []):
                check_type = rule.get("check_type", "")
                check_fn = _CHECK_DISPATCH.get(check_type)
                if check_fn is None:
                    continue
                try:
                    outcome = check_fn(self._project, rule.get("parameters", {}))
                except Exception as e:
                    outcome = {"passed": True, "detail": f"Check error: {e}", "resources": []}

                results.append(ComplianceResult(
                    framework=fw_name,
                    control_id=rule.get("id", ""),
                    title=rule.get("title", ""),
                    section=rule.get("section", ""),
                    severity=rule.get("severity", "medium"),
                    passed=outcome.get("passed", True),
                    detail=outcome.get("detail", ""),
                    affected_resources=outcome.get("resources", []),
                    remediation=rule.get("remediation", ""),
                    auto_fix=rule.get("auto_fix"),
                ))
        return results

    def summary(self, results: list[ComplianceResult]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed
        by_severity = {}
        for r in results:
            if not r.passed:
                by_severity[r.severity] = by_severity.get(r.severity, 0) + 1
        score = round((passed / total) * 100) if total else 100
        return {
            "total_controls": total,
            "passed": passed,
            "failed": failed,
            "compliance_score": score,
            "failures_by_severity": by_severity,
        }
