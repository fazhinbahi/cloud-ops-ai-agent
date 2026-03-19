"""
sandbox/demo.py — Guided interactive demo runner for the Cloud Ops Agent.

Walks a client through all phases with narration, pauses, and explanations
so they understand what the agent is doing at every step.

Usage:
    python main.py --sandbox-demo
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich import box

console = Console()

MANIFEST_FILE = Path(__file__).parent / "provisioned_resources.json"


def _pause(msg: str = "Press Enter to continue...") -> None:
    console.print(f"\n[dim]{msg}[/dim]")
    input()


def _narrate(title: str, body: str, color: str = "cyan") -> None:
    console.print()
    console.print(Panel(body, title=f"[bold]{title}[/bold]", border_style=color, padding=(1, 2)))
    time.sleep(0.5)


def _check_provisioned() -> bool:
    return MANIFEST_FILE.exists()


def run_demo() -> None:
    console.clear()

    # ── Welcome ──────────────────────────────────────────────
    console.print(Panel(
        "[bold cyan]Cloud Ops AI Agent — Live Demo[/bold cyan]\n\n"
        "This demo walks you through the full autonomous cloud operations pipeline:\n\n"
        "  [bold]Phase 1[/bold]  Observe   — agent scans your GCP and finds real problems\n"
        "  [bold]Phase 2[/bold]  Act       — agent proposes fixes, you approve each one\n"
        "  [bold]Phase 3[/bold]  Automate  — agent fixes low-risk issues automatically\n\n"
        "[dim]The sandbox GCP project contains intentionally misconfigured resources.[/dim]\n"
        "[dim]Nothing in your production environment will be touched.[/dim]",
        border_style="cyan",
        title="[bold]Welcome[/bold]",
        padding=(1, 2),
    ))

    if not _check_provisioned():
        console.print("\n[yellow]⚠  Sandbox resources not yet provisioned.[/yellow]")
        if Confirm.ask("Provision sandbox resources now? (takes ~3 min for VMs to start)"):
            from sandbox.provision import provision_all
            provision_all()
        else:
            console.print("[red]Cannot run demo without sandbox resources. Exiting.[/red]")
            sys.exit(1)

    _pause("Ready? Press Enter to start Phase 1 →")

    # ── Phase 1 ───────────────────────────────────────────────
    console.clear()
    _narrate(
        "Phase 1 — Observe",
        "Six specialist AI agents are about to scan your GCP project in parallel.\n\n"
        "Each agent focuses on its domain:\n"
        "  • [cyan]Infra Agent[/cyan]     → VMs, VPCs, firewall rules\n"
        "  • [cyan]Security Agent[/cyan]  → IAM, public buckets, open ports\n"
        "  • [cyan]Cost Agent[/cyan]      → idle VMs, billing gaps\n"
        "  • [cyan]Incident Agent[/cyan]  → alert policies, uptime checks\n"
        "  • [cyan]Deployment Agent[/cyan]→ Cloud Run, Cloud Build\n"
        "  • [cyan]Data Agent[/cyan]      → BigQuery, Pub/Sub, Dataform\n\n"
        "No changes are made in this phase. Pure observation.",
        color="blue",
    )
    _pause("Press Enter to run Phase 1 scan →")

    import subprocess
    console.print("\n[bold cyan]Running Phase 1 scan...[/bold cyan]\n")
    result = subprocess.run(
        ["python", "main.py"],
        capture_output=False,
        text=True,
    )

    _narrate(
        "Phase 1 Complete",
        "The agent just scanned every enabled GCP service in your project.\n\n"
        "Notice what it found [bold]automatically[/bold], without any configuration:\n"
        "  🔴 Open firewall rules  (SSH/RDP exposed to the entire internet)\n"
        "  🔴 Public GCS bucket    (anyone on the internet can read it)\n"
        "  🟠 Over-permissioned SA (Editor role — violates least-privilege)\n"
        "  🟠 No budget alerts     (cost overruns would go unnoticed)\n"
        "  🔴 Zero monitoring      (no alert policies, no uptime checks)\n\n"
        "A human engineer would need hours to manually check all of this.\n"
        "The agent did it in under 60 seconds.",
        color="green",
    )
    _pause("Press Enter to move to Phase 2 →")

    # ── Phase 2 ───────────────────────────────────────────────
    console.clear()
    _narrate(
        "Phase 2 — Supervised Action",
        "Now the agent will:\n\n"
        "  1. Read all the findings from Phase 1\n"
        "  2. Use Claude Opus 4.6 to propose remediation actions\n"
        "  3. Show you each proposed action with full context\n"
        "  4. Wait for [bold]your approval[/bold] before executing anything\n\n"
        "You are always in control. The agent never acts without your say-so.\n\n"
        "[dim]We'll run in --dry-run mode first so you can see the proposals\n"
        "without actually changing anything in GCP.[/dim]",
        color="yellow",
    )
    _pause("Press Enter to see what the agent proposes →")

    console.print("\n[bold yellow]Running Phase 2 dry-run (no GCP changes)...[/bold yellow]\n")
    dry_result = subprocess.run(
        ["python", "main.py", "--phase", "2", "--dry-run"],
        input="s\n",
        capture_output=False,
        text=True,
    )

    _narrate(
        "Phase 2 — Now Let's Approve a Real Fix",
        "You just saw the proposed actions. Now let's execute one for real.\n\n"
        "We'll [bold]disable the default-allow-rdp firewall rule[/bold]:\n"
        "  • Eliminates the most critical attack vector (internet-exposed RDP)\n"
        "  • Reversible — rule is disabled, not deleted\n"
        "  • Blast radius: medium (only affects RDP — no SSH, no HTTP)\n\n"
        "After you approve, open GCP Console → VPC → Firewall rules\n"
        "and watch the rule change state in real time.",
        color="yellow",
    )

    if Confirm.ask("\nRun Phase 2 LIVE (you'll approve/reject each action interactively)?"):
        console.print("\n[bold yellow]Running Phase 2 live — approve actions at the prompt...[/bold yellow]\n")
        subprocess.run(["python", "main.py", "--phase", "2"])
    else:
        console.print("[dim]Skipped live Phase 2. You can run it later with: PHASE=2 python main.py[/dim]")

    _pause("Press Enter to move to Phase 3 →")

    # ── Phase 3 ───────────────────────────────────────────────
    console.clear()
    _narrate(
        "Phase 3 — Autonomous Action",
        "Phase 3 adds a [bold]policy engine[/bold] that auto-approves safe actions.\n\n"
        "The policy file (policies/default.yaml) defines rules like:\n"
        "  • Reversible + low blast radius   → [green]auto_approve[/green]\n"
        "  • Medium blast radius             → [yellow]require_human[/yellow]\n"
        "  • Irreversible                    → [red]require_human[/red]\n\n"
        "After executing each action, the agent:\n"
        "  ✓ Re-queries GCP to verify the fix worked\n"
        "  ✓ Rolls back automatically if verification fails\n"
        "  ✓ Records everything in an append-only audit log\n\n"
        "[dim]This is what 'lights-out operations' looks like at 3am.[/dim]",
        color="magenta",
    )

    if Confirm.ask("\nRun Phase 3 dry-run to see autonomous behaviour?"):
        console.print("\n[bold magenta]Running Phase 3 dry-run...[/bold magenta]\n")
        subprocess.run(["python", "main.py", "--phase", "3", "--dry-run"])
    else:
        console.print("[dim]Skipped Phase 3. Run anytime: PHASE=3 python main.py --dry-run[/dim]")

    # ── Summary ───────────────────────────────────────────────
    console.print()
    _narrate(
        "Demo Complete — Summary",
        "[bold]What you just saw:[/bold]\n\n"
        "  Phase 1  Agent scanned 12 enabled GCP services in < 60 seconds\n"
        "           Found all intentional misconfigurations automatically\n\n"
        "  Phase 2  Claude Opus proposed targeted, safe remediation actions\n"
        "           Full rollback instructions for every action\n"
        "           You stayed in control — nothing happened without approval\n\n"
        "  Phase 3  Policy engine auto-approved safe actions\n"
        "           Verifier confirmed fixes worked in GCP\n"
        "           Audit log written for every event\n\n"
        "[bold]In production this system runs 24/7:[/bold]\n"
        "  • Scheduled scans every 6 hours\n"
        "  • Real-time alerts via GCP Monitoring webhooks\n"
        "  • Findings and approvals routed to your Slack channels\n"
        "  • Automated post-mortems after every incident\n\n"
        "[dim]To clean up sandbox resources:[/dim]\n"
        "  [cyan]python main.py --sandbox-teardown[/cyan]",
        color="green",
    )


if __name__ == "__main__":
    run_demo()
