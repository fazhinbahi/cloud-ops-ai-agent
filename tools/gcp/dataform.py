"""GCP Dataform — read-only repository and workflow inspection."""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT

PROJECT = GOOGLE_CLOUD_PROJECT


def list_dataform_repositories() -> list[dict[str, Any]]:
    """List Dataform repositories and their Git remote status."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("dataform", "v1beta1", credentials=credentials)
        result = service.projects().locations().repositories().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()
        return [{
            "name": r.get("name", "").split("/")[-1],
            "region": r.get("name", "").split("/")[3] if "/" in r.get("name", "") else "",
            "git_remote": r.get("gitRemoteSettings", {}).get("url", "none"),
            "git_auth_token_set": bool(r.get("gitRemoteSettings", {}).get("authenticationTokenSecretVersion")),
        } for r in result.get("repositories", [])]
    except Exception as e:
        return [{"error": str(e)}]


def list_dataform_workflow_invocations() -> list[dict[str, Any]]:
    """List recent Dataform workflow invocations to detect failures."""
    try:
        from googleapiclient import discovery
        import google.auth
        credentials, _ = google.auth.default()
        service = discovery.build("dataform", "v1beta1", credentials=credentials)

        # First get repositories
        repos_result = service.projects().locations().repositories().list(
            parent=f"projects/{PROJECT}/locations/-"
        ).execute()

        invocations = []
        for repo in repos_result.get("repositories", [])[:5]:  # limit to 5 repos
            try:
                inv_result = service.projects().locations().repositories().workflowInvocations().list(
                    parent=repo["name"],
                    pageSize=5,
                ).execute()
                for inv in inv_result.get("workflowInvocations", []):
                    invocations.append({
                        "repository": repo["name"].split("/")[-1],
                        "name": inv.get("name", "").split("/")[-1],
                        "state": inv.get("state"),
                        "invocation_config": inv.get("invocationConfig", {}).get("fullyRefreshIncrementalTablesEnabled"),
                    })
            except Exception:
                continue
        return invocations
    except Exception as e:
        return [{"error": str(e)}]


DESCRIPTOR = {
    "api": "dataform.googleapis.com",
    "display_name": "Dataform",
    "domains": ["data"],
    "tools": [list_dataform_repositories, list_dataform_workflow_invocations],
}
