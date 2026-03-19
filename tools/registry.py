"""
tools/registry.py — Service Registry for the Cloud Ops agent system.

HOW IT WORKS
────────────
Every file in tools/gcp/ declares a DESCRIPTOR dict:

    DESCRIPTOR = {
        "api":          "datafusion.googleapis.com",   # GCP API identifier
        "display_name": "Cloud Data Fusion",
        "domains":      ["data"],                      # which agents own this
        "tools":        [list_data_fusion_instances],  # callable tool functions
    }

The registry:
  1. Auto-discovers all tools/gcp/*.py modules at first use
  2. Queries the GCP Service Usage API to find which APIs are enabled
  3. Filters tools to only those whose API is actually on
  4. Provides tools grouped by agent domain

ADDING A NEW SERVICE
────────────────────
Create tools/gcp/my_service.py with a DESCRIPTOR.
That's it — no other file needs changing.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable

# domain → list of (descriptor, tool_fn)
_registry: dict[str, list[tuple[dict, Callable]]] = {}
_enabled_apis: set[str] | None = None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_all_descriptors() -> None:
    """Import every tools/gcp/*.py module and collect DESCRIPTOR dicts."""
    global _registry
    if _registry:
        return  # already loaded

    import tools.gcp as gcp_pkg
    for _, module_name, _ in pkgutil.iter_modules(gcp_pkg.__path__):
        try:
            module = importlib.import_module(f"tools.gcp.{module_name}")
        except Exception:
            continue

        descriptor = getattr(module, "DESCRIPTOR", None)
        if descriptor is None:
            continue

        # Support both "domain" (singular) and "domains" (list)
        domains = descriptor.get("domains") or [descriptor.get("domain")]
        for domain in domains:
            if domain not in _registry:
                _registry[domain] = []
            for fn in descriptor.get("tools", []):
                _registry[domain].append((descriptor, fn))


def _get_enabled_apis() -> set[str]:
    """
    Query GCP Service Usage API once and cache the result.
    Returns a set of enabled API names like 'compute.googleapis.com'.
    If the query fails, returns an empty set (tools will be included by default).
    """
    global _enabled_apis
    if _enabled_apis is not None:
        return _enabled_apis

    try:
        from googleapiclient import discovery
        import google.auth
        from config import GOOGLE_CLOUD_PROJECT

        credentials, _ = google.auth.default()
        service = discovery.build("serviceusage", "v1", credentials=credentials)
        result = service.services().list(
            parent=f"projects/{GOOGLE_CLOUD_PROJECT}",
            filter="state:ENABLED",
            pageSize=200,
        ).execute()
        _enabled_apis = {
            s["name"].split("/")[-1]
            for s in result.get("services", [])
        }
    except Exception:
        # Fail open — can't determine enabled APIs, include everything
        _enabled_apis = set()

    return _enabled_apis


def _is_enabled(descriptor: dict) -> bool:
    """Return True if this service's API is enabled (or if we couldn't check)."""
    api = descriptor.get("api")
    enabled = _get_enabled_apis()
    # Empty set means we couldn't check — include everything
    return not api or not enabled or api in enabled


# ── Public API ────────────────────────────────────────────────────────────────

def get_tools_for_domain(domain: str) -> list[tuple[dict, Callable]]:
    """
    Return (descriptor, tool_fn) pairs for the given domain,
    filtered to APIs that are actually enabled in the GCP project.
    """
    _load_all_descriptors()
    return [
        (descriptor, fn)
        for descriptor, fn in _registry.get(domain, [])
        if _is_enabled(descriptor)
    ]


def get_active_domains() -> list[str]:
    """Return all domains that have at least one enabled service registered."""
    _load_all_descriptors()
    return [
        domain
        for domain in _registry
        if any(_is_enabled(d) for d, _ in _registry[domain])
    ]


def list_all_services() -> list[dict[str, Any]]:
    """
    Return all registered services with their enabled status.
    Useful for 'python main.py --list-services'.
    """
    _load_all_descriptors()
    enabled = _get_enabled_apis()

    seen: set[str] = set()
    services = []
    for domain, items in _registry.items():
        for descriptor, _ in items:
            key = descriptor.get("api", descriptor.get("display_name", ""))
            if key in seen:
                continue
            seen.add(key)
            services.append({
                "api": descriptor.get("api", ""),
                "display_name": descriptor.get("display_name", ""),
                "domains": descriptor.get("domains", [descriptor.get("domain")]),
                "enabled": not enabled or descriptor.get("api", "") in enabled,
            })
    return sorted(services, key=lambda x: x["display_name"])


def get_unmonitored_apis() -> list[str]:
    """
    Return enabled GCP APIs that have no registered module.

    These are coverage gaps — services running in the project that Phase 1
    cannot observe. Each one is a candidate for a new tools/gcp/<name>.py.

    System/infrastructure APIs that have no useful monitoring surface are
    excluded from this list automatically.
    """
    _load_all_descriptors()
    enabled = _get_enabled_apis()
    if not enabled:
        return []

    # APIs that are always enabled by GCP internally — no resources to monitor
    SYSTEM_APIS = {
        "cloudapis.googleapis.com",
        "oslogin.googleapis.com",
        "servicemanagement.googleapis.com",
        "serviceusage.googleapis.com",
        "sql-component.googleapis.com",
        "storage-api.googleapis.com",
        "storage-component.googleapis.com",
        "bigquerymigration.googleapis.com",
        "bigquerystorage.googleapis.com",
        "bigquerydatapolicy.googleapis.com",   # covered via bigquery_extended
        "analyticshub.googleapis.com",          # covered via bigquery_extended
        "bigqueryreservation.googleapis.com",   # covered via bigquery_extended
        "bigquerydatatransfer.googleapis.com",  # covered via bigquery_extended
        "bigqueryconnection.googleapis.com",    # covered via bigquery_extended
    }

    # APIs we already have a module for
    registered_apis: set[str] = set()
    for items in _registry.values():
        for descriptor, _ in items:
            api = descriptor.get("api")
            if api:
                registered_apis.add(api)

    return sorted(
        api for api in enabled
        if api not in registered_apis and api not in SYSTEM_APIS
    )


def invalidate_cache() -> None:
    """Clear cached registry and enabled-API list (useful in tests or after config change)."""
    global _registry, _enabled_apis
    _registry = {}
    _enabled_apis = None
