"""
tools/aws/iam.py — AWS IAM observation tools.
"""
from __future__ import annotations
from typing import Any


def list_iam_users() -> dict[str, Any]:
    """Return all IAM users with MFA status and last activity."""
    try:
        import boto3
        iam = boto3.client("iam")
        paginator = iam.get_paginator("list_users")
        users = []
        for page in paginator.paginate():
            for user in page["Users"]:
                mfa = iam.list_mfa_devices(UserName=user["UserName"])
                users.append({
                    "username": user["UserName"],
                    "created": str(user.get("CreateDate", "")),
                    "last_used": str(user.get("PasswordLastUsed", "never")),
                    "mfa_enabled": len(mfa.get("MFADevices", [])) > 0,
                    "arn": user.get("Arn", ""),
                })
        return {"users": users, "count": len(users)}
    except Exception as e:
        return {"error": str(e)}


def list_iam_roles_with_admin() -> dict[str, Any]:
    """Return IAM roles that have AdministratorAccess policy attached."""
    try:
        import boto3
        iam = boto3.client("iam")
        admin_roles = []
        paginator = iam.get_paginator("list_roles")
        for page in paginator.paginate():
            for role in page["Roles"]:
                attached = iam.list_attached_role_policies(RoleName=role["RoleName"])
                for policy in attached.get("AttachedPolicies", []):
                    if policy["PolicyName"] == "AdministratorAccess":
                        admin_roles.append({
                            "role_name": role["RoleName"],
                            "arn": role["Arn"],
                            "policy": "AdministratorAccess",
                        })
        return {"admin_roles": admin_roles, "count": len(admin_roles)}
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "cloud":        "aws",
    "api":          "iam.amazonaws.com",
    "display_name": "AWS IAM",
    "domains":      ["security"],
    "tools":        [list_iam_users, list_iam_roles_with_admin],
}
