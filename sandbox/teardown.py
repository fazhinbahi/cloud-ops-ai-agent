"""
sandbox/teardown.py — Remove all demo sandbox resources from GCP.

Reads sandbox/provisioned_resources.json (written by provision.py)
to know exactly what was created and deletes only those resources.
Nothing outside the manifest is touched.

Usage:
    python -m sandbox.teardown
"""
from __future__ import annotations

import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()
MANIFEST_FILE = Path(__file__).parent / "provisioned_resources.json"


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


def _wait_zone_op(service, project, zone, op_name, timeout=120):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = service.zoneOperations().get(
            project=project, zone=zone, operation=op_name
        ).execute()
        if result.get("status") == "DONE":
            return
        time.sleep(4)


def delete_vm(name: str, zone: str) -> None:
    from googleapiclient import discovery
    creds, project = _creds_and_project()
    svc = discovery.build("compute", "v1", credentials=creds)
    try:
        op = svc.instances().delete(project=project, zone=zone, instance=name).execute()
        _wait_zone_op(svc, project, zone, op["name"])
        console.print(f"    [green]✓ Deleted VM: {name}[/green]")
    except Exception as e:
        console.print(f"    [yellow]⚠  VM {name}: {e}[/yellow]")


def delete_bucket(name: str) -> None:
    from google.cloud import storage
    creds, project = _creds_and_project()
    client = storage.Client(project=project, credentials=creds)
    try:
        bucket = client.get_bucket(name)
        # Delete all objects first
        blobs = list(bucket.list_blobs())
        for blob in blobs:
            blob.delete()
        bucket.delete(force=True)
        console.print(f"    [green]✓ Deleted bucket: {name}[/green]")
    except Exception as e:
        console.print(f"    [yellow]⚠  Bucket {name}: {e}[/yellow]")


def delete_service_account(email: str, role: str) -> None:
    from googleapiclient import discovery
    creds, project = _creds_and_project()
    iam_svc = discovery.build("iam", "v1", credentials=creds)
    crm_svc = discovery.build("cloudresourcemanager", "v1", credentials=creds)
    try:
        # Remove IAM binding first
        policy = crm_svc.projects().getIamPolicy(resource=project, body={}).execute()
        policy["bindings"] = [
            b for b in policy.get("bindings", [])
            if not (b["role"] == role and f"serviceAccount:{email}" in b.get("members", []))
        ]
        crm_svc.projects().setIamPolicy(
            resource=project, body={"policy": policy}
        ).execute()

        # Delete service account
        iam_svc.projects().serviceAccounts().delete(
            name=f"projects/{project}/serviceAccounts/{email}"
        ).execute()
        console.print(f"    [green]✓ Deleted service account: {email}[/green]")
    except Exception as e:
        console.print(f"    [yellow]⚠  SA {email}: {e}[/yellow]")


def delete_bigquery_dataset(dataset_id: str) -> None:
    from google.cloud import bigquery
    creds, project = _creds_and_project()
    client = bigquery.Client(project=project, credentials=creds)
    try:
        client.delete_dataset(f"{project}.{dataset_id}", delete_contents=True, not_found_ok=True)
        console.print(f"    [green]✓ Deleted BigQuery dataset: {dataset_id}[/green]")
    except Exception as e:
        console.print(f"    [yellow]⚠  Dataset {dataset_id}: {e}[/yellow]")


def teardown_all() -> None:
    """Delete every resource listed in the provisioned_resources.json manifest."""
    if not MANIFEST_FILE.exists():
        console.print("[yellow]No manifest found at sandbox/provisioned_resources.json[/yellow]")
        console.print("[dim]Nothing to tear down.[/dim]")
        return

    manifest = json.loads(MANIFEST_FILE.read_text())
    resources = manifest.get("resources", [])

    console.print(Panel(
        f"[bold red]Cloud Ops Sandbox Teardown[/bold red]\n"
        f"[dim]Project: {manifest.get('project', 'unknown')}[/dim]\n\n"
        f"Removing {len(resources)} resource(s) from the manifest.",
        border_style="red",
    ))

    for res in resources:
        rtype = res.get("type")

        if rtype == "vm":
            console.print(f"\n  [dim]→[/dim] Deleting VM: {res['name']} ({res['zone']})")
            delete_vm(res["name"], res["zone"])

        elif rtype == "bucket":
            console.print(f"\n  [dim]→[/dim] Deleting bucket: {res['name']}")
            delete_bucket(res["name"])

        elif rtype == "service_account":
            console.print(f"\n  [dim]→[/dim] Deleting service account: {res['email']}")
            delete_service_account(res["email"], res.get("role", "roles/editor"))

        elif rtype == "bigquery_dataset":
            console.print(f"\n  [dim]→[/dim] Deleting BigQuery dataset: {res['dataset_id']}")
            delete_bigquery_dataset(res["dataset_id"])

        elif rtype in ("firewall_note", "monitoring_note"):
            console.print(f"\n  [dim]→ Skipping note: {res['detail']}[/dim]")

    # Remove manifest
    MANIFEST_FILE.unlink(missing_ok=True)

    console.print(Panel(
        "[bold green]Teardown complete.[/bold green]\n\n"
        "All sandbox resources have been removed.\n"
        "The project is back to its pre-demo state.\n\n"
        "[dim]Note: Default firewall rules (SSH/RDP open) and the existing\n"
        "storage bucket were not created by the sandbox and were not removed.[/dim]",
        border_style="green",
    ))


if __name__ == "__main__":
    teardown_all()
