"""
tools/gcp_actions/storage.py — GCS bucket write actions.

All functions return a result dict: {"success": bool, "message": str, "before": ..., "after": ...}
"""
from __future__ import annotations
from typing import Any
from config import GOOGLE_CLOUD_PROJECT


def remove_bucket_public_access(
    project: str,
    bucket_name: str,
    member_to_remove: str,
    role: str,
) -> dict[str, Any]:
    """
    Remove a public IAM binding (allUsers or allAuthenticatedUsers) from a GCS bucket.

    Only removes the specific member+role pair. Other bindings are untouched.
    The removed binding is recorded in the return value for rollback reference.

    Rollback: re-add the binding via bucket.get_iam_policy() + set_iam_policy().
    """
    project = project or GOOGLE_CLOUD_PROJECT
    try:
        from google.cloud import storage
        import google.auth
        credentials, _ = google.auth.default()
        client = storage.Client(project=project, credentials=credentials)
        bucket = client.bucket(bucket_name)

        policy = bucket.get_iam_policy(requested_policy_version=3)

        # Record before state
        before_bindings = [
            {"role": b.get("role"), "members": list(b.get("members", []))}
            for b in policy.bindings
        ]

        # Remove the specific member from the specific role binding
        removed = False
        for binding in policy.bindings:
            if binding.get("role") == role and member_to_remove in binding.get("members", set()):
                binding["members"].discard(member_to_remove)
                removed = True
                break

        if not removed:
            return {
                "success": False,
                "message": f"Member '{member_to_remove}' with role '{role}' not found on bucket '{bucket_name}'.",
                "before": before_bindings,
                "after": before_bindings,
            }

        # Remove any bindings that now have no members
        policy.bindings = [b for b in policy.bindings if b.get("members")]
        bucket.set_iam_policy(policy)

        return {
            "success": True,
            "message": (
                f"Removed '{member_to_remove}' ({role}) from bucket '{bucket_name}'. "
                f"Bucket is no longer publicly accessible via this binding."
            ),
            "before": before_bindings,
            "after": [
                {"role": b.get("role"), "members": list(b.get("members", []))}
                for b in policy.bindings
            ],
            "rollback": (
                f"Re-add binding: role='{role}', member='{member_to_remove}' "
                f"to bucket '{bucket_name}' via GCP Console > Storage > {bucket_name} > Permissions."
            ),
        }
    except Exception as e:
        return {"success": False, "message": str(e), "before": {}, "after": {}}
