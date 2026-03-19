"""
tools/reporting_tools.py — Reporting and notification utilities.

Phase 1: Write findings to stdout (with rich formatting) and to disk.
Phase 2+: Integrate Slack, PagerDuty, Jira, email.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from memory.store import Finding, FindingsStore
from config import REPORT_OUTPUT_DIR, SLACK_WEBHOOK_URL

console = Console()

SEVERITY_COLOR = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "info": "white",
}

SEVERITY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🔵",
    "info": "⚪",
}


def print_findings_table(findings: list[Finding]) -> None:
    """Print findings as a rich table to stdout."""
    if not findings:
        console.print("[green]✓ No findings.[/green]")
        return

    table = Table(
        title="Cloud Ops Findings",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("Severity", style="bold", width=10)
    table.add_column("Agent", width=12)
    table.add_column("Title", width=40)
    table.add_column("Resource", width=25)
    table.add_column("Region", width=12)

    for f in sorted(findings, key=lambda x: ["critical","high","medium","low","info"].index(x.severity)):
        color = SEVERITY_COLOR.get(f.severity, "white")
        table.add_row(
            f"[{color}]{SEVERITY_EMOJI[f.severity]} {f.severity.upper()}[/{color}]",
            f.agent,
            f.title,
            f.resource or "—",
            f.region or "—",
        )

    console.print(table)


def print_agent_report(agent: str, findings: list[Finding]) -> None:
    """Print a panel summary for a single agent."""
    lines = []
    for f in findings:
        color = SEVERITY_COLOR.get(f.severity, "white")
        lines.append(f"[{color}]{SEVERITY_EMOJI[f.severity]} [{f.severity.upper()}][/{color}] {f.title}")
        if f.detail:
            lines.append(f"  [dim]{f.detail[:120]}[/dim]")

    body = "\n".join(lines) if lines else "[green]No issues found.[/green]"
    console.print(Panel(body, title=f"[bold]{agent.upper()} AGENT[/bold]", border_style="blue"))


def save_report_to_disk(store: FindingsStore, run_id: str | None = None) -> Path:
    """Persist findings to disk and return the file path."""
    path = store.flush_to_disk(run_id=run_id)
    console.print(f"\n[dim]Report saved → {path}[/dim]")
    return path


def post_to_slack(findings: list[Finding], webhook_url: str = SLACK_WEBHOOK_URL) -> bool:
    """
    Post a summary of high/critical findings to Slack.
    Returns True on success, False if webhook not configured or request fails.
    """
    if not webhook_url:
        return False

    import urllib.request
    import urllib.error

    critical = [f for f in findings if f.severity in ("critical", "high")]
    if not critical:
        return True  # Nothing urgent to post

    lines = [f"*Cloud Ops Alert — {len(critical)} High/Critical Finding(s)*\n"]
    for f in critical[:10]:  # Cap at 10 to avoid huge messages
        lines.append(f"• {SEVERITY_EMOJI[f.severity]} *[{f.severity.upper()}]* {f.title} ({f.agent})")
        if f.resource:
            lines.append(f"  Resource: `{f.resource}`")

    payload = json.dumps({"text": "\n".join(lines)}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        return True
    except urllib.error.URLError:
        return False
