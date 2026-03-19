"""
tools/aws_tools.py — Read-only AWS observation tools.

PHASE 1 RULE: Every function here is READ-ONLY.
No create/update/delete/modify calls. Observe, never act.

These are plain Python functions. Each agent will import and call them,
then hand the results to the LLM for interpretation.
"""

import json
from typing import Any

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from config import AWS_DEFAULT_REGION


def _client(service: str, region: str = AWS_DEFAULT_REGION):
    return boto3.client(service, region_name=region)


def _safe(fn, *args, **kwargs) -> dict:
    """Wrap any boto3 call so it never raises — returns error as data."""
    try:
        return fn(*args, **kwargs)
    except NoCredentialsError:
        return {"error": "AWS credentials not configured. Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env"}
    except ClientError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"Unexpected error: {e}"}


# ══════════════════════════════════════════════
# INFRASTRUCTURE TOOLS
# ══════════════════════════════════════════════

def list_ec2_instances(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return all EC2 instances with their state, type, and tags."""
    ec2 = _client("ec2", region)

    def _call():
        paginator = ec2.get_paginator("describe_instances")
        instances = []
        for page in paginator.paginate():
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    name = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        inst["InstanceId"],
                    )
                    instances.append({
                        "id": inst["InstanceId"],
                        "name": name,
                        "type": inst["InstanceType"],
                        "state": inst["State"]["Name"],
                        "az": inst.get("Placement", {}).get("AvailabilityZone", ""),
                        "launch_time": str(inst.get("LaunchTime", "")),
                        "private_ip": inst.get("PrivateIpAddress", ""),
                        "public_ip": inst.get("PublicIpAddress", ""),
                    })
        return {"instances": instances, "count": len(instances)}

    return _safe(_call)


def list_rds_instances(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return all RDS instances with their status, engine, and size."""
    rds = _client("rds", region)

    def _call():
        resp = rds.describe_db_instances()
        dbs = []
        for db in resp["DBInstances"]:
            dbs.append({
                "id": db["DBInstanceIdentifier"],
                "engine": db["Engine"],
                "version": db["EngineVersion"],
                "class": db["DBInstanceClass"],
                "status": db["DBInstanceStatus"],
                "multi_az": db["MultiAZ"],
                "storage_gb": db["AllocatedStorage"],
                "publicly_accessible": db["PubliclyAccessible"],
            })
        return {"instances": dbs, "count": len(dbs)}

    return _safe(_call)


def list_eks_clusters(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return all EKS cluster names and their status."""
    eks = _client("eks", region)

    def _call():
        clusters = eks.list_clusters()["clusters"]
        details = []
        for name in clusters:
            info = eks.describe_cluster(name=name)["cluster"]
            details.append({
                "name": name,
                "status": info["status"],
                "version": info["version"],
                "endpoint": info.get("endpoint", ""),
                "role_arn": info.get("roleArn", ""),
            })
        return {"clusters": details, "count": len(details)}

    return _safe(_call)


def list_vpcs(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return all VPCs and their CIDR blocks."""
    ec2 = _client("ec2", region)

    def _call():
        vpcs = ec2.describe_vpcs()["Vpcs"]
        result = []
        for v in vpcs:
            name = next(
                (t["Value"] for t in v.get("Tags", []) if t["Key"] == "Name"), v["VpcId"]
            )
            result.append({
                "id": v["VpcId"],
                "name": name,
                "cidr": v["CidrBlock"],
                "is_default": v["IsDefault"],
                "state": v["State"],
            })
        return {"vpcs": result, "count": len(result)}

    return _safe(_call)


# ══════════════════════════════════════════════
# COST TOOLS
# ══════════════════════════════════════════════

def get_cost_last_30_days(region: str = "us-east-1") -> dict:
    """Return total AWS spend for the last 30 days, broken down by service."""
    ce = _client("ce", "us-east-1")  # Cost Explorer is global, always us-east-1

    from datetime import datetime, timedelta
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    def _call():
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        services = []
        for result in resp["ResultsByTime"]:
            for group in result["Groups"]:
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                if amount > 0.01:
                    services.append({
                        "service": group["Keys"][0],
                        "cost_usd": round(amount, 2),
                    })
        services.sort(key=lambda x: x["cost_usd"], reverse=True)
        total = sum(s["cost_usd"] for s in services)
        return {"period": f"{start} to {end}", "total_usd": round(total, 2), "by_service": services}

    return _safe(_call)


def get_cost_anomalies(region: str = "us-east-1") -> dict:
    """Return recent cost anomalies detected by AWS Cost Anomaly Detection."""
    ce = _client("ce", "us-east-1")

    from datetime import datetime, timedelta
    end = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    start = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _call():
        resp = ce.get_anomalies(
            DateInterval={"StartDate": start, "EndDate": end},
            MaxResults=20,
        )
        anomalies = []
        for a in resp.get("Anomalies", []):
            anomalies.append({
                "id": a["AnomalyId"],
                "service": a.get("AnomalyDetails", {}).get("ServiceName", "Unknown"),
                "impact_usd": a.get("Impact", {}).get("TotalImpact", 0),
                "start_date": a.get("AnomalyStartDate", ""),
                "end_date": a.get("AnomalyEndDate", "ongoing"),
                "root_causes": a.get("RootCauses", []),
            })
        return {"anomalies": anomalies, "count": len(anomalies)}

    return _safe(_call)


def list_idle_ec2_instances(region: str = AWS_DEFAULT_REGION) -> dict:
    """
    Return EC2 instances that appear idle:
    stopped instances or instances with 't2/t3.micro' type running for >30 days.
    (Phase 1: heuristic scan — no CloudWatch metric analysis yet.)
    """
    result = list_ec2_instances(region)
    if "error" in result:
        return result

    from datetime import datetime, timezone
    idle = []
    for inst in result["instances"]:
        if inst["state"] == "stopped":
            idle.append({**inst, "reason": "Instance is stopped but still incurring EBS costs"})
    return {"idle_instances": idle, "count": len(idle)}


# ══════════════════════════════════════════════
# SECURITY TOOLS
# ══════════════════════════════════════════════

def list_public_s3_buckets() -> dict:
    """Return S3 buckets that have public access enabled."""
    s3 = _client("s3", "us-east-1")

    def _call():
        buckets = s3.list_buckets()["Buckets"]
        public_buckets = []
        for bucket in buckets:
            name = bucket["Name"]
            try:
                acl = s3.get_bucket_acl(Bucket=name)
                for grant in acl.get("Grants", []):
                    grantee = grant.get("Grantee", {})
                    if grantee.get("URI", "").endswith("AllUsers") or grantee.get("URI", "").endswith("AuthenticatedUsers"):
                        public_buckets.append({"name": name, "reason": "ACL grants public access"})
                        break
            except ClientError:
                pass  # Skip buckets we don't have access to describe

            try:
                block = s3.get_public_access_block(Bucket=name)
                cfg = block.get("PublicAccessBlockConfiguration", {})
                if not all([
                    cfg.get("BlockPublicAcls", False),
                    cfg.get("BlockPublicPolicy", False),
                    cfg.get("IgnorePublicAcls", False),
                    cfg.get("RestrictPublicBuckets", False),
                ]):
                    if not any(b["name"] == name for b in public_buckets):
                        public_buckets.append({"name": name, "reason": "Public access block not fully enabled"})
            except ClientError:
                pass

        return {"public_buckets": public_buckets, "count": len(public_buckets)}

    return _safe(_call)


def list_open_security_groups(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return security groups with rules open to 0.0.0.0/0 on sensitive ports."""
    ec2 = _client("ec2", region)
    SENSITIVE_PORTS = {22, 3389, 3306, 5432, 6379, 27017, 9200}

    def _call():
        sgs = ec2.describe_security_groups()["SecurityGroups"]
        risky = []
        for sg in sgs:
            for rule in sg.get("IpPermissions", []):
                from_port = rule.get("FromPort", 0)
                to_port = rule.get("ToPort", 65535)
                for ip_range in rule.get("IpRanges", []):
                    if ip_range.get("CidrIp") == "0.0.0.0/0":
                        exposed_ports = [
                            p for p in SENSITIVE_PORTS
                            if from_port <= p <= to_port
                        ]
                        if exposed_ports or (from_port == 0 and to_port == 65535):
                            risky.append({
                                "sg_id": sg["GroupId"],
                                "name": sg["GroupName"],
                                "vpc_id": sg.get("VpcId", ""),
                                "exposed_ports": exposed_ports or ["ALL"],
                                "cidr": "0.0.0.0/0",
                            })
                            break
        return {"risky_security_groups": risky, "count": len(risky)}

    return _safe(_call)


def list_iam_users_without_mfa() -> dict:
    """Return IAM users that do not have MFA enabled."""
    iam = _client("iam", "us-east-1")

    def _call():
        users = iam.list_users()["Users"]
        no_mfa = []
        for user in users:
            mfa = iam.list_mfa_devices(UserName=user["UserName"])["MFADevices"]
            if not mfa:
                no_mfa.append({
                    "username": user["UserName"],
                    "created": str(user.get("CreateDate", "")),
                    "last_used": str(user.get("PasswordLastUsed", "never")),
                })
        return {"users_without_mfa": no_mfa, "count": len(no_mfa)}

    return _safe(_call)


# ══════════════════════════════════════════════
# INCIDENT / MONITORING TOOLS
# ══════════════════════════════════════════════

def list_cloudwatch_alarms(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return CloudWatch alarms that are currently in ALARM state."""
    cw = _client("cloudwatch", region)

    def _call():
        resp = cw.describe_alarms(StateValue="ALARM")
        alarms = []
        for alarm in resp["MetricAlarms"]:
            alarms.append({
                "name": alarm["AlarmName"],
                "description": alarm.get("AlarmDescription", ""),
                "metric": alarm.get("MetricName", ""),
                "namespace": alarm.get("Namespace", ""),
                "state_reason": alarm.get("StateReason", ""),
                "state_updated": str(alarm.get("StateUpdatedTimestamp", "")),
            })
        return {"active_alarms": alarms, "count": len(alarms)}

    return _safe(_call)


def get_ec2_health_status(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return EC2 instances with failed system or instance status checks."""
    ec2 = _client("ec2", region)

    def _call():
        resp = ec2.describe_instance_status(
            Filters=[{"Name": "instance-status.status", "Values": ["impaired"]}]
        )
        unhealthy = []
        for s in resp["InstanceStatuses"]:
            unhealthy.append({
                "id": s["InstanceId"],
                "system_status": s["SystemStatus"]["Status"],
                "instance_status": s["InstanceStatus"]["Status"],
                "az": s["AvailabilityZone"],
            })
        return {"unhealthy_instances": unhealthy, "count": len(unhealthy)}

    return _safe(_call)


# ══════════════════════════════════════════════
# DEPLOYMENT TOOLS
# ══════════════════════════════════════════════

def list_ecs_services(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return ECS services with their running vs desired task counts."""
    ecs = _client("ecs", region)

    def _call():
        cluster_arns = ecs.list_clusters()["clusterArns"]
        services_summary = []
        for cluster_arn in cluster_arns:
            service_arns = ecs.list_services(cluster=cluster_arn)["serviceArns"]
            if not service_arns:
                continue
            services = ecs.describe_services(cluster=cluster_arn, services=service_arns)["services"]
            for svc in services:
                is_healthy = svc["runningCount"] >= svc["desiredCount"]
                services_summary.append({
                    "name": svc["serviceName"],
                    "cluster": cluster_arn.split("/")[-1],
                    "desired": svc["desiredCount"],
                    "running": svc["runningCount"],
                    "pending": svc["pendingCount"],
                    "status": svc["status"],
                    "healthy": is_healthy,
                    "launch_type": svc.get("launchType", ""),
                })
        return {"services": services_summary, "count": len(services_summary)}

    return _safe(_call)


def list_codepipeline_failures(region: str = AWS_DEFAULT_REGION) -> dict:
    """Return CodePipeline pipelines that are currently in a failed state."""
    cp = _client("codepipeline", region)

    def _call():
        pipelines = cp.list_pipelines()["pipelines"]
        failed = []
        for p in pipelines:
            state = cp.get_pipeline_state(name=p["name"])
            for stage in state["stageStates"]:
                stage_status = stage.get("latestExecution", {}).get("status", "")
                if stage_status == "Failed":
                    failed.append({
                        "pipeline": p["name"],
                        "stage": stage["stageName"],
                        "status": stage_status,
                        "error": stage.get("latestExecution", {}).get("errorDetails", {}).get("message", ""),
                    })
                    break
        return {"failed_pipelines": failed, "count": len(failed)}

    return _safe(_call)
