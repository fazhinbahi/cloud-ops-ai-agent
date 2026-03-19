"""
tools/aws/ec2.py — AWS EC2 observation tools.

DESCRIPTOR follows the same pattern as tools/gcp/ modules so the
multi-cloud registry picks it up automatically.
"""
from __future__ import annotations
from typing import Any
from config import AWS_DEFAULT_REGION


def list_ec2_instances() -> dict[str, Any]:
    """Return all EC2 instances with their state, type, launch time, and tags."""
    try:
        import boto3
        from botocore.exceptions import NoCredentialsError, ClientError
        ec2 = boto3.client("ec2", region_name=AWS_DEFAULT_REGION)
        paginator = ec2.get_paginator("describe_instances")
        instances = []
        for page in paginator.paginate():
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), ""
                    )
                    instances.append({
                        "id": inst["InstanceId"],
                        "name": name,
                        "type": inst.get("InstanceType", ""),
                        "state": inst["State"]["Name"],
                        "launch_time": str(inst.get("LaunchTime", "")),
                        "region": AWS_DEFAULT_REGION,
                        "public_ip": inst.get("PublicIpAddress", ""),
                    })
        return {"instances": instances, "count": len(instances)}
    except Exception as e:
        return {"error": str(e)}


def list_idle_ec2_instances() -> dict[str, Any]:
    """Return EC2 instances that have been stopped for more than 7 days."""
    try:
        import boto3
        from datetime import datetime, timezone, timedelta
        ec2 = boto3.client("ec2", region_name=AWS_DEFAULT_REGION)
        paginator = ec2.get_paginator("describe_instances")
        idle = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        for page in paginator.paginate(Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]):
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    state_reason = inst.get("StateTransitionReason", "")
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), inst["InstanceId"]
                    )
                    idle.append({
                        "id": inst["InstanceId"],
                        "name": name,
                        "type": inst.get("InstanceType", ""),
                        "state": "stopped",
                        "state_reason": state_reason,
                        "region": AWS_DEFAULT_REGION,
                    })
        return {"idle_instances": idle, "count": len(idle)}
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "cloud":        "aws",
    "api":          "ec2.amazonaws.com",
    "display_name": "AWS EC2",
    "domains":      ["infra", "cost"],
    "tools":        [list_ec2_instances, list_idle_ec2_instances],
}
