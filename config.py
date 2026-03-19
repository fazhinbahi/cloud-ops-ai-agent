"""
config.py — Central configuration for the Cloud Ops Multi-Agent System.

All credentials are loaded from environment variables or a .env file.
Never hardcode secrets here.
"""

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


# ──────────────────────────────────────────────
# Claude API
# ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Use Opus 4.6 for the Supervisor (complex reasoning / routing)
# Use Sonnet 4.6 for specialist agents (cost-efficient, still very capable)
SUPERVISOR_MODEL = "claude-opus-4-6"
SPECIALIST_MODEL = "claude-sonnet-4-6"


# ──────────────────────────────────────────────
# GCP Credentials  (used by google-cloud SDKs)
# ──────────────────────────────────────────────
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")

# Set ADC path so google-auth picks up the service account key
if GOOGLE_APPLICATION_CREDENTIALS:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(
        GOOGLE_APPLICATION_CREDENTIALS
    )


# ──────────────────────────────────────────────
# Phase control
# ──────────────────────────────────────────────
# PHASE 1: Observe only — collect findings, never act.
# PHASE 2: Supervised action — propose → human approves → execute.
# PHASE 3: Autonomous action — policy-based auto-approval, self-healing, pattern detection.
PHASE = int(os.getenv("PHASE", "1"))

# Backwards-compatible alias used in Phase 1 code paths.
OBSERVE_ONLY = PHASE < 2

# ──────────────────────────────────────────────
# Phase 2 — Action controls
# ──────────────────────────────────────────────
# Always True in Phase 2: every action requires a human to type [y].
REQUIRE_APPROVAL = True

# DRY_RUN: simulate actions without touching GCP. Audit log still written.
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# CONFIRM_DESTRUCTIVE: must be True to be prompted for irreversible actions.
# Without this flag, irreversible actions are auto-rejected at the approval gate.
CONFIRM_DESTRUCTIVE = os.getenv("CONFIRM_DESTRUCTIVE", "false").lower() == "true"

# Maximum actions the proposal engine may return per run.
MAX_PROPOSED_ACTIONS = int(os.getenv("MAX_PROPOSED_ACTIONS", "10"))


# ──────────────────────────────────────────────
# Phase 3 — Autonomous action controls
# ──────────────────────────────────────────────
# Path to the YAML policy file that defines auto-approval rules.
POLICY_FILE = os.getenv("POLICY_FILE", "./policies/default.yaml")

# AUTO_ROLLBACK: if post-execution verification fails, automatically roll back.
AUTO_ROLLBACK = os.getenv("AUTO_ROLLBACK", "true").lower() == "true"

# VERIFY_AFTER_EXECUTE: re-run the relevant tool after execution to confirm fix.
VERIFY_AFTER_EXECUTE = os.getenv("VERIFY_AFTER_EXECUTE", "true").lower() == "true"

# How many days back to look when detecting recurring findings patterns.
PATTERN_WINDOW_DAYS = int(os.getenv("PATTERN_WINDOW_DAYS", "30"))

# How many times a finding must recur before it is flagged as a pattern.
PATTERN_RECURRENCE_THRESHOLD = int(os.getenv("PATTERN_RECURRENCE_THRESHOLD", "3"))

# Path to the SQLite database used for cross-run history and pattern detection.
HISTORY_DB = os.getenv("HISTORY_DB", "./memory/history.db")

# EVENT_LISTENER_PORT: port for the webhook server that receives GCP Monitoring alerts.
EVENT_LISTENER_PORT = int(os.getenv("EVENT_LISTENER_PORT", "8080"))


# ──────────────────────────────────────────────
# Phase 4 — Predictive, Compliance, Runbooks, ChatOps, Multi-cloud
# ──────────────────────────────────────────────

# Predictor: how many past runs to use for trend analysis.
PREDICTOR_LOOKBACK_RUNS = int(os.getenv("PREDICTOR_LOOKBACK_RUNS", "10"))

# Compliance: path to compliance framework definitions.
COMPLIANCE_FRAMEWORKS_DIR = os.getenv("COMPLIANCE_FRAMEWORKS_DIR", "./compliance/frameworks")

# Runbooks: path to runbook YAML library.
RUNBOOKS_DIR = os.getenv("RUNBOOKS_DIR", "./runbooks/library")

# Slack ChatOps (Phase 4 two-way bot via Socket Mode).
SLACK_BOT_TOKEN   = os.getenv("SLACK_BOT_TOKEN", "")     # xoxb-...
SLACK_APP_TOKEN   = os.getenv("SLACK_APP_TOKEN", "")     # xapp-... (Socket Mode)
SLACK_OPS_CHANNEL = os.getenv("SLACK_OPS_CHANNEL", "#cloud-ops")

# AWS credentials for multi-cloud support (Phase 4).
AWS_ACCESS_KEY_ID     = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
AWS_DEFAULT_REGION    = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
AWS_ENABLED           = bool(AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY)


# ──────────────────────────────────────────────
# Phase 5 — FinOps, RCA, IaC Drift, SLO, Multi-Tenant, Post-Mortems
# ──────────────────────────────────────────────

# FinOps: how many days of Cloud Monitoring metrics to analyse for rightsizing.
FINOPS_METRICS_WINDOW_DAYS = int(os.getenv("FINOPS_METRICS_WINDOW_DAYS", "30"))

# FinOps: VMs whose average CPU < this threshold are flagged as idle candidates.
FINOPS_CPU_IDLE_THRESHOLD = float(os.getenv("FINOPS_CPU_IDLE_THRESHOLD", "0.10"))

# FinOps: spend increase > this fraction vs 7-day average triggers cost anomaly.
FINOPS_COST_ANOMALY_THRESHOLD = float(os.getenv("FINOPS_COST_ANOMALY_THRESHOLD", "0.20"))

# RCA: enable multi-signal root cause analysis after incidents.
RCA_ENABLED = os.getenv("RCA_ENABLED", "true").lower() == "true"

# IaC: path to terraform.tfstate for drift detection (leave blank to skip).
IAC_STATE_FILE = os.getenv("IAC_STATE_FILE", "")

# IaC: if True, fixes are pushed as GitHub PRs instead of direct API calls.
IAC_GITOPS_MODE = os.getenv("IAC_GITOPS_MODE", "false").lower() == "true"

# GitHub credentials for IaC GitOps PR creation.
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO  = os.getenv("GITHUB_REPO", "")   # format: "owner/repo"

# SLO: path to YAML file defining service level objectives.
SLO_DEFINITIONS_FILE = os.getenv("SLO_DEFINITIONS_FILE", "./slo/definitions.yaml")

# SLO: alert when error budget burn rate would exhaust budget before month end.
SLO_BURN_RATE_ALERT_THRESHOLD = float(os.getenv("SLO_BURN_RATE_ALERT_THRESHOLD", "2.0"))

# Multi-tenant: path to YAML file defining teams and their scopes.
TENANTS_CONFIG_FILE = os.getenv("TENANTS_CONFIG_FILE", "./tenants/config.yaml")

# Post-mortems: directory for generated Markdown post-mortem reports.
POSTMORTEMS_DIR = os.getenv("POSTMORTEMS_DIR", "./postmortems/reports")


# ──────────────────────────────────────────────
# Notification / Reporting (Phase 1: file + stdout)
# ──────────────────────────────────────────────
REPORT_OUTPUT_DIR = os.getenv("REPORT_OUTPUT_DIR", "./reports")

# Optional Slack webhook — if set, findings are also posted to Slack
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")


# ──────────────────────────────────────────────
# Agent run settings
# ──────────────────────────────────────────────
class AgentConfig(BaseModel):
    name: str
    description: str
    model: str
    max_turns: int = 10


AGENT_CONFIGS = {
    "infra": AgentConfig(
        name="Infrastructure Agent",
        description="Monitors VPCs, Compute Engine instances, GKE clusters, Cloud SQL, and overall infra health.",
        model=SPECIALIST_MODEL,
    ),
    "cost": AgentConfig(
        name="Cost Agent",
        description="Monitors GCP spend via Cloud Billing, detects anomalies, identifies idle/oversized resources.",
        model=SPECIALIST_MODEL,
    ),
    "security": AgentConfig(
        name="Security Agent",
        description="Monitors IAM policies, firewall rules, public GCS buckets, and compliance drift.",
        model=SPECIALIST_MODEL,
    ),
    "incident": AgentConfig(
        name="Incident Agent",
        description="Monitors Cloud Monitoring alerts, checks for unhealthy resources, surfaces active incidents.",
        model=SPECIALIST_MODEL,
    ),
    "deployment": AgentConfig(
        name="Deployment Agent",
        description="Monitors Cloud Run service health, GKE workloads, Cloud Build pipeline status.",
        model=SPECIALIST_MODEL,
    ),
}
