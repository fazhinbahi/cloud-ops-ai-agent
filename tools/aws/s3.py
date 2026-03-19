"""
tools/aws/s3.py — AWS S3 observation tools.
"""
from __future__ import annotations
from typing import Any


def list_s3_buckets() -> dict[str, Any]:
    """Return all S3 buckets with creation date and region."""
    try:
        import boto3
        s3 = boto3.client("s3")
        response = s3.list_buckets()
        buckets = []
        for b in response.get("Buckets", []):
            try:
                location = s3.get_bucket_location(Bucket=b["Name"])
                region = location.get("LocationConstraint") or "us-east-1"
            except Exception:
                region = "unknown"
            buckets.append({
                "name": b["Name"],
                "created": str(b.get("CreationDate", "")),
                "region": region,
            })
        return {"buckets": buckets, "count": len(buckets)}
    except Exception as e:
        return {"error": str(e)}


def list_public_s3_buckets() -> dict[str, Any]:
    """Return S3 buckets with public access not blocked."""
    try:
        import boto3
        s3 = boto3.client("s3")
        response = s3.list_buckets()
        public = []
        for b in response.get("Buckets", []):
            try:
                cfg = s3.get_public_access_block(Bucket=b["Name"])
                block = cfg["PublicAccessBlockConfiguration"]
                if not all([
                    block.get("BlockPublicAcls"),
                    block.get("BlockPublicPolicy"),
                    block.get("IgnorePublicAcls"),
                    block.get("RestrictPublicBuckets"),
                ]):
                    public.append({"name": b["Name"], "reason": "public_access_block_not_fully_enabled"})
            except s3.exceptions.NoSuchPublicAccessBlockConfiguration:
                public.append({"name": b["Name"], "reason": "no_public_access_block_configured"})
            except Exception:
                pass
        return {"public_buckets": public, "count": len(public)}
    except Exception as e:
        return {"error": str(e)}


DESCRIPTOR = {
    "cloud":        "aws",
    "api":          "s3.amazonaws.com",
    "display_name": "AWS S3",
    "domains":      ["security", "cost"],
    "tools":        [list_s3_buckets, list_public_s3_buckets],
}
