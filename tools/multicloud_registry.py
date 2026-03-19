"""
tools/multicloud_registry.py — Phase 4 multi-cloud tool registry.

Extends the GCP service registry to also include AWS modules from tools/aws/.
AWS modules are only loaded when AWS_ENABLED=True (credentials are set).

Usage:
    from tools.multicloud_registry import get_tools_for_domain_multicloud

    tools = get_tools_for_domain_multicloud("security")
    # returns [(descriptor, tool_fn), ...] from both GCP and AWS
"""
from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import AWS_ENABLED


@lru_cache(maxsize=None)
def _load_aws_descriptors() -> dict[str, list[tuple[dict, Any]]]:
    """
    Discover all tools/aws/*.py modules and index their DESCRIPTORs by domain.
    Returns {domain: [(descriptor, tool_fn), ...]}
    """
    registry: dict[str, list] = {}
    aws_pkg_path = str(Path(__file__).parent / "aws")

    try:
        import tools.aws as aws_pkg
    except ImportError:
        return registry

    for finder, module_name, _ in pkgutil.iter_modules([aws_pkg_path]):
        try:
            mod = importlib.import_module(f"tools.aws.{module_name}")
        except Exception:
            continue

        descriptor = getattr(mod, "DESCRIPTOR", None)
        if not isinstance(descriptor, dict):
            continue

        for domain in descriptor.get("domains", []):
            if domain not in registry:
                registry[domain] = []
            for tool_fn in descriptor.get("tools", []):
                registry[domain].append((descriptor, tool_fn))

    return registry


def get_tools_for_domain_multicloud(domain: str) -> list[tuple[dict, Any]]:
    """
    Return all tools (GCP + AWS) registered for a given agent domain.
    AWS tools are only included when AWS_ENABLED is True.
    """
    from tools.registry import get_tools_for_domain as gcp_tools
    tools = list(gcp_tools(domain))

    if AWS_ENABLED:
        aws_registry = _load_aws_descriptors()
        tools.extend(aws_registry.get(domain, []))

    return tools


def list_all_clouds() -> list[dict]:
    """Return a summary of all registered cloud services (GCP + AWS)."""
    from tools.registry import list_all_services
    services = [{"cloud": "gcp", **s} for s in list_all_services()]

    if AWS_ENABLED:
        aws_registry = _load_aws_descriptors()
        seen: set[str] = set()
        for domain, tools in aws_registry.items():
            for descriptor, _ in tools:
                api = descriptor.get("api", "")
                if api not in seen:
                    seen.add(api)
                    services.append({
                        "cloud": "aws",
                        "api": api,
                        "display_name": descriptor.get("display_name", api),
                        "domains": descriptor.get("domains", []),
                        "enabled": True,
                    })

    return services


def invalidate_aws_cache() -> None:
    _load_aws_descriptors.cache_clear()
