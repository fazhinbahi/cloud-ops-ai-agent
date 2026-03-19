"""
sandbox/provision.py — Provision intentionally misconfigured GCP resources
for the Cloud Ops Agent demo sandbox.

Creates the following "broken" resources so the agent has real things to find:
  - 2 VM instances  (1 running idle, 1 stopped/forgotten)
  - 1 public GCS bucket  (allUsers readable — security finding)
  - 1 over-permissioned service account  (Editor role — IAM finding)
  - 1 BigQuery dataset  (no data governance)
  - Open firewall rules  (SSH/RDP to 0.0.0.0/0 — already present by default)
  - No monitoring / alerting  (zero alert policies — already present by default)

All created resources are tagged with label  sandbox=cloudops-demo
so teardown can find and delete them precisely.

Usage:
    python -m sandbox.provision
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

SANDBOX_LABEL_KEY   = "sandbox"
SANDBOX_LABEL_VALUE = "cloudops-demo"
MANIFEST_FILE       = Path(__file__).parent / "provisioned_resources.json"

# All VMs go here — cheapest region + smallest machine type
DEFAULT_ZONE    = "us-central1-a"
DEFAULT_MACHINE = "e2-micro"
DEFAULT_IMAGE   = "projects/debian-cloud/global/images/family/debian-12"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _creds_and_project():
    import os
    from config import GOOGLE_CLOUD_PROJECT
    key_file = os.environ.get("SANDBOX_GOOGLE_APPLICATION_CREDENTIALS")
    if key_file:
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_file(
            key_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
    else:
        import google.auth
        credentials, _ = google.auth.default()
    return credentials, GOOGLE_CLOUD_PROJECT


def _wait_zone_op(service, project: str, zone: str, op_name: str, timeout: int = 180):
    """Poll a zonal Compute operation until DONE."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = service.zoneOperations().get(
            project=project, zone=zone, operation=op_name
        ).execute()
        if result.get("status") == "DONE":
            if "error" in result:
                raise RuntimeError(f"GCP operation error: {result['error']}")
            return
        time.sleep(4)
    raise TimeoutError(f"Operation {op_name} timed out after {timeout}s")


# ─────────────────────────────────────────────────────────────
# Resource creators
# ─────────────────────────────────────────────────────────────

def create_vm(name: str, zone: str = DEFAULT_ZONE, stop_after: bool = False) -> dict:
    """
    Create an e2-micro VM.
    If stop_after=True the VM is stopped immediately after creation
    (simulates a forgotten / idle stopped instance).
    """
    from googleapiclient import discovery
    creds, project = _creds_and_project()
    svc = discovery.build("compute", "v1", credentials=creds)

    body = {
        "name": name,
        "machineType": f"zones/{zone}/machineTypes/{DEFAULT_MACHINE}",
        "labels": {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE},
        "disks": [{
            "boot": True,
            "autoDelete": True,
            "initializeParams": {"sourceImage": DEFAULT_IMAGE},
        }],
        "networkInterfaces": [{
            "network": f"projects/{project}/global/networks/default",
            "accessConfigs": [{"type": "ONE_TO_ONE_NAT", "name": "External NAT"}],
        }],
        "metadata": {
            "items": [{"key": "purpose", "value": "cloudops-sandbox-demo"}]
        },
    }

    op = svc.instances().insert(project=project, zone=zone, body=body).execute()
    _wait_zone_op(svc, project, zone, op["name"])

    if stop_after:
        stop_op = svc.instances().stop(
            project=project, zone=zone, instance=name
        ).execute()
        _wait_zone_op(svc, project, zone, stop_op["name"])
        final_status = "TERMINATED"
    else:
        final_status = "RUNNING"

    return {"type": "vm", "name": name, "zone": zone, "status": final_status}


def create_public_bucket(project: str) -> dict:
    """Create a GCS bucket and grant allUsers objectViewer (public read)."""
    from google.cloud import storage
    creds, project = _creds_and_project()
    client = storage.Client(project=project, credentials=creds)

    bucket_name = f"cloudops-demo-public-{project[:18]}"
    bucket = client.bucket(bucket_name)
    bucket.labels = {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE}
    bucket = client.create_bucket(bucket, location="US")

    # Disable uniform bucket-level access so we can set legacy public ACL
    bucket.iam_configuration.uniform_bucket_level_access_enabled = False
    bucket.patch()

    # Make public
    policy = bucket.get_iam_policy(requested_policy_version=1)
    policy.bindings.append({
        "role": "roles/storage.objectViewer",
        "members": {"allUsers"},
    })
    bucket.set_iam_policy(policy)

    return {"type": "bucket", "name": bucket_name}


def create_overpermissioned_sa(project: str) -> dict:
    """Create a service account and bind it the Editor role."""
    from googleapiclient import discovery
    creds, project = _creds_and_project()
    iam_svc = discovery.build("iam", "v1", credentials=creds)
    crm_svc = discovery.build("cloudresourcemanager", "v1", credentials=creds)

    sa_id = "sandbox-demo-sa"

    # Create the service account
    sa = iam_svc.projects().serviceAccounts().create(
        name=f"projects/{project}",
        body={
            "accountId": sa_id,
            "serviceAccount": {
                "displayName": "Sandbox Demo — Over-permissioned SA",
                "description": "Intentionally overpermissioned for Cloud Ops agent demo",
            },
        },
    ).execute()
    sa_email = sa["email"]

    # Bind Editor role on the project
    current_policy = crm_svc.projects().getIamPolicy(
        resource=project, body={}
    ).execute()
    current_policy.setdefault("bindings", []).append({
        "role": "roles/editor",
        "members": [f"serviceAccount:{sa_email}"],
    })
    crm_svc.projects().setIamPolicy(
        resource=project,
        body={"policy": current_policy},
    ).execute()

    return {"type": "service_account", "email": sa_email, "role": "roles/editor"}


def create_bigquery_dataset(project: str) -> dict:
    """Create a BigQuery dataset with no special access controls (uses project defaults)."""
    from google.cloud import bigquery
    creds, project = _creds_and_project()
    client = bigquery.Client(project=project, credentials=creds)

    dataset_id = "sandbox_demo_dataset"
    dataset = bigquery.Dataset(f"{project}.{dataset_id}")
    dataset.location = "US"
    dataset.labels = {SANDBOX_LABEL_KEY: SANDBOX_LABEL_VALUE}
    client.create_dataset(dataset, exists_ok=True)

    return {"type": "bigquery_dataset", "dataset_id": dataset_id}


# ─────────────────────────────────────────────────────────────
# Main provisioner
# ─────────────────────────────────────────────────────────────

def provision_all(skip_vm: bool = False) -> None:
    """
    Provision all sandbox resources.
    Pass skip_vm=True to skip VM creation (saves time / cost if VMs already exist).
    """
    _, project = _creds_and_project()

    console.print(Panel(
        f"[bold cyan]Cloud Ops Sandbox Provisioner[/bold cyan]\n"
        f"[dim]Project: {project}[/dim]\n\n"
        "Creating intentionally misconfigured resources for the demo.\n"
        "The agent will find and (optionally) fix all of these.",
        border_style="cyan",
    ))

    manifest = {"project": project, "resources": []}

    steps = []
    if not skip_vm:
        steps += [
            (
                "🖥️  VM #1 — idle-sandbox-vm-1  (RUNNING, no workload)",
                lambda: create_vm("idle-sandbox-vm-1", stop_after=False),
                "Infra/Cost agent will flag as idle running VM",
            ),
            (
                "🖥️  VM #2 — idle-sandbox-vm-2  (STOPPED, forgotten)",
                lambda: create_vm("idle-sandbox-vm-2", stop_after=True),
                "Cost agent will flag as stopped/orphaned resource",
            ),
        ]

    steps += [
        (
            "🪣  Public GCS bucket  (allUsers = objectViewer)",
            lambda: create_public_bucket(project),
            "Security agent will flag as PUBLIC bucket — CRITICAL",
        ),
        (
            "🔑  Service account  sandbox-demo-sa  (Editor role)",
            lambda: create_overpermissioned_sa(project),
            "Security agent will flag over-permissioned SA — HIGH",
        ),
        (
            "📊  BigQuery dataset  sandbox_demo_dataset",
            lambda: create_bigquery_dataset(project),
            "Data agent will flag missing access controls",
        ),
    ]

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Resource", style="cyan", width=48)
    table.add_column("What the agent finds", width=45)
    table.add_column("Status", width=10)

    for description, fn, finding in steps:
        console.print(f"\n  [dim]→[/dim] {description}")
        try:
            result = fn()
            manifest["resources"].append(result)
            table.add_row(description, finding, "[green]✓ Created[/green]")
            console.print(f"    [green]✓ Done[/green]")
        except Exception as e:
            table.add_row(description, finding, "[yellow]⚠ Skipped[/yellow]")
            console.print(f"    [yellow]⚠  Skipped ({e})[/yellow]")

    # Always note that firewall + monitoring gaps already exist
    manifest["resources"].append({
        "type": "firewall_note",
        "detail": "default-allow-ssh and default-allow-rdp open to 0.0.0.0/0 (pre-existing)",
    })
    manifest["resources"].append({
        "type": "monitoring_note",
        "detail": "Zero alert policies / uptime checks (pre-existing default state)",
    })

    MANIFEST_FILE.write_text(json.dumps(manifest, indent=2))

    console.print()
    console.print(table)
    console.print(Panel(
        "[bold green]Sandbox ready![/bold green]\n\n"
        "Run the demo:\n"
        "  [cyan]python main.py --sandbox-demo[/cyan]\n\n"
        "Or run manually:\n"
        "  [cyan]python main.py[/cyan]                  ← Phase 1 observe\n"
        "  [cyan]PHASE=2 python main.py --dry-run[/cyan] ← Phase 2 dry-run\n"
        "  [cyan]PHASE=2 python main.py[/cyan]           ← Phase 2 live approve\n\n"
        "To clean up all demo resources:\n"
        "  [cyan]python main.py --sandbox-teardown[/cyan]",
        border_style="green",
        title="[bold]Next Steps[/bold]",
    ))


if __name__ == "__main__":
    provision_all()
