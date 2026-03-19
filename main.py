"""
main.py — Entry point for the Cloud Ops Multi-Agent System.

PHASE 1 (default):
    python main.py                          # observe-only full cycle
    python main.py --agent security         # run one agent

PHASE 2 (supervised action):
    PHASE=2 python main.py                  # observe → propose → approve → execute
    PHASE=2 python main.py --dry-run        # simulate actions, no GCP changes
    PHASE=2 python main.py --confirm-destructive  # allow irreversible actions

PHASE 3 (autonomous):
    PHASE=3 python main.py                  # policy-based auto-approve + verify + rollback
    PHASE=3 python main.py --dry-run        # simulate Phase 3 pipeline, no GCP changes
    PHASE=3 python main.py --listen         # also start webhook server for GCP alerts

PHASE 4 (predictive + proactive):
    PHASE=4 python main.py                  # predict + compliance + observe + runbooks
    PHASE=4 python main.py --slack          # also start two-way Slack bot
    PHASE=4 python main.py --dry-run        # full Phase 4 pipeline, no GCP changes
    python main.py --compliance             # run CIS GCP compliance scan only
    python main.py --predict                # run predictive forecast only
    python main.py --runbooks               # list loaded runbooks
    python main.py --list-clouds            # show all registered services (GCP + AWS)

PHASE 5 (intelligent + proactive + multi-tenant):
    PHASE=5 python main.py                  # full Phase 5: FinOps + SLO + IaC + RCA + post-mortem
    PHASE=5 python main.py --dry-run        # simulate everything, no GCP changes
    python main.py --finops                 # run FinOps analysis only
    python main.py --slo                    # evaluate SLOs only
    python main.py --iac-drift              # run IaC drift detection only
    python main.py --rca                    # run RCA on latest findings
    python main.py --postmortem RUN_ID      # generate post-mortem for a completed run
    python main.py --tenants                # show team configuration

UTILITIES:
    python main.py --list-services          # show all GCP services + enabled status
    python main.py --scaffold cloudfunctions.googleapis.com   # generate stub module
    python main.py --history                # show cross-run pattern summary
    python main.py --policy                 # show loaded policy rules
"""
from __future__ import annotations

import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _apply_cli_overrides(args: argparse.Namespace) -> None:
    """Inject CLI flags into environment before config is imported by other modules."""
    if args.phase is not None:
        os.environ["PHASE"] = str(args.phase)
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    if args.confirm_destructive:
        os.environ["CONFIRM_DESTRUCTIVE"] = "true"


def validate_config() -> bool:
    from config import ANTHROPIC_API_KEY
    if not ANTHROPIC_API_KEY:
        console.print("[red]ERROR: ANTHROPIC_API_KEY is not set.[/red]")
        console.print("Copy .env.example to .env and fill in your API key.")
        return False
    return True


def check_coverage() -> None:
    from tools.scaffolder import coverage_report
    report = coverage_report()
    if report["gap_count"] == 0:
        return
    console.print(Panel(
        f"[yellow bold]{report['gap_count']} enabled API(s) have no monitoring module.[/yellow bold]\n"
        + "\n".join(
            f"  [dim]•[/dim] [cyan]{g['api']}[/cyan]  "
            f"[dim](suggested domain: {g['suggested_domain']})[/dim]\n"
            f"    [dim]→ {g['scaffold_cmd']}[/dim]"
            for g in report["gaps"]
        ),
        title="[yellow]Coverage Gaps[/yellow]",
        border_style="yellow",
    ))


def run_full_cycle(trigger: str) -> None:
    from agents.supervisor import SupervisorAgent
    supervisor = SupervisorAgent()
    result = supervisor.run(trigger=trigger)
    console.print(f"\n[dim]Run complete. ID: {result['run_id']}[/dim]")
    console.print(f"[dim]Report: {result['report_path']}[/dim]")


def run_single_agent(agent_name: str) -> None:
    from agents.supervisor import _build_domain_map
    from memory.store import store
    from tools.reporting_tools import print_agent_report, save_report_to_disk

    domain_map = _build_domain_map()
    AgentClass = domain_map.get(agent_name)
    if not AgentClass:
        console.print(f"[red]Unknown agent: {agent_name}[/red]")
        console.print(f"Available: {', '.join(sorted(domain_map.keys()))}")
        sys.exit(1)

    agent = AgentClass()
    findings = agent.run()
    print_agent_report(agent.name, findings)
    path = save_report_to_disk(store)
    console.print(f"\n[dim]Report saved: {path}[/dim]")


def list_services() -> None:
    from tools.registry import list_all_services
    services = list_all_services()
    table = Table(title="Registered GCP Services", show_lines=True)
    table.add_column("Service", style="cyan")
    table.add_column("API", style="dim")
    table.add_column("Domain(s)", style="yellow")
    table.add_column("Enabled", justify="center")
    for svc in services:
        enabled_str = "[green]✓[/green]" if svc["enabled"] else "[red]✗[/red]"
        table.add_row(
            svc["display_name"], svc["api"],
            ", ".join(svc.get("domains", [])), enabled_str,
        )
    console.print(table)
    console.print("\n[dim]Add a service: create tools/gcp/<name>.py with a DESCRIPTOR.[/dim]")


def show_history() -> None:
    from memory.history import history_db
    summary = history_db.summary()
    table = Table(title=f"Cross-Run History (last {summary['window_days']} days)", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")
    table.add_row("Total findings recorded", str(summary["total_findings"]))
    table.add_row("Total actions recorded", str(summary["total_actions"]))
    table.add_row("Recurring patterns", str(summary["recurring_patterns"]))
    console.print(table)

    patterns = summary["top_patterns"]
    if patterns:
        pt = Table(title="Top Recurring Patterns", show_lines=True)
        pt.add_column("Resource", style="cyan", width=30)
        pt.add_column("Check Type", style="yellow", width=20)
        pt.add_column("Occurrences", justify="right")
        pt.add_column("Last Seen", width=25)
        for p in patterns:
            pt.add_row(p["resource"], p["check_type"], str(p["occurrences"]), p["last_seen"][:19])
        console.print(pt)
    else:
        console.print("[dim]No recurring patterns found in the history window.[/dim]")


def show_policy() -> None:
    from agents.policy_engine import PolicyEngine
    import yaml
    from pathlib import Path
    from config import POLICY_FILE

    policy = PolicyEngine()
    s = policy.summary()
    console.print(Panel(
        f"Policy file:     [cyan]{s['policy_file']}[/cyan]\n"
        f"Rules loaded:    [bold]{s['rules_loaded']}[/bold]\n"
        f"Default decision: [yellow]{s['default_decision']}[/yellow]",
        title="[bold]Phase 3 Policy[/bold]",
        border_style="cyan",
    ))

    path = Path(POLICY_FILE)
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text())
            rules = data.get("rules", [])
            table = Table(title="Policy Rules (evaluated top-to-bottom)", show_lines=True)
            table.add_column("#", justify="right", style="dim", width=3)
            table.add_column("Name", style="cyan", width=35)
            table.add_column("Decision", width=15)
            table.add_column("Conditions", width=50)
            for i, rule in enumerate(rules, 1):
                conditions = []
                if rule.get("action_types"):
                    conditions.append(f"action_types={rule['action_types']}")
                if rule.get("blast_radius"):
                    conditions.append(f"blast_radius={rule['blast_radius']}")
                if rule.get("reversibility"):
                    conditions.append(f"reversibility={rule['reversibility']}")
                color = "green" if rule.get("decision") == "auto_approve" else "yellow"
                table.add_row(
                    str(i), rule.get("name", ""),
                    f"[{color}]{rule.get('decision', '')}[/{color}]",
                    " | ".join(conditions) or "[dim]match all[/dim]",
                )
            console.print(table)
        except Exception as e:
            console.print(f"[yellow]Could not parse policy file: {e}[/yellow]")


def run_compliance() -> None:
    from agents.compliance_agent import ComplianceAgent
    agent = ComplianceAgent()
    agent.run()


def run_predict() -> None:
    from agents.predictor import Predictor
    from rich.table import Table
    predictor = Predictor()
    predictions = predictor.run()
    if not predictions:
        console.print("[dim]No predictive forecasts generated. Run more cycles to build history.[/dim]")
        return
    table = Table(title="Predictive Forecasts", show_lines=True)
    table.add_column("Resource", style="cyan", width=28)
    table.add_column("Prediction", width=42)
    table.add_column("Confidence", width=10)
    table.add_column("Recommended Action", width=35)
    for p in predictions:
        conf_color = "green" if p.confidence == "high" else "yellow" if p.confidence == "medium" else "dim"
        table.add_row(
            p.resource, p.prediction[:41],
            f"[{conf_color}]{p.confidence}[/{conf_color}]",
            p.recommended_action[:34],
        )
    console.print(table)


def list_runbooks() -> None:
    from runbooks.engine import RunbookEngine
    from audit.log import AuditLogger
    engine = RunbookEngine(audit_logger=AuditLogger(run_id="list"), dry_run=True)
    # Access internal list
    rbs = engine._runbooks
    if not rbs:
        console.print("[dim]No runbooks loaded. Add YAML files to runbooks/library/.[/dim]")
        return
    table = Table(title="Loaded Runbooks", show_lines=True)
    table.add_column("ID", style="cyan", width=20)
    table.add_column("Name", width=35)
    table.add_column("Triggers", width=35)
    table.add_column("Steps", justify="right", width=6)
    table.add_column("Severity Threshold", width=18)
    for rb in rbs:
        table.add_row(
            rb.get("id", ""), rb.get("name", ""),
            ", ".join(rb.get("trigger_patterns", [])[:3]),
            str(len(rb.get("steps", []))),
            rb.get("severity_threshold", "high"),
        )
    console.print(table)


def list_clouds() -> None:
    from tools.multicloud_registry import list_all_clouds
    from config import AWS_ENABLED
    services = list_all_clouds()
    table = Table(title="Registered Services (All Clouds)", show_lines=True)
    table.add_column("Cloud", width=6)
    table.add_column("Service", style="cyan", width=20)
    table.add_column("API", style="dim", width=35)
    table.add_column("Domain(s)", style="yellow", width=25)
    table.add_column("Enabled", justify="center", width=8)
    for svc in services:
        enabled_str = "[green]✓[/green]" if svc.get("enabled") else "[red]✗[/red]"
        cloud_str = f"[{'cyan' if svc['cloud'] == 'gcp' else 'yellow'}]{svc['cloud'].upper()}[/]"
        table.add_row(
            cloud_str, svc.get("display_name", ""), svc.get("api", ""),
            ", ".join(svc.get("domains", [])), enabled_str,
        )
    console.print(table)
    if not AWS_ENABLED:
        console.print("[dim]AWS not enabled — set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env[/dim]")


def start_slack_bot() -> None:
    from integrations.slack_bot import slack_bot
    from config import PHASE
    if not slack_bot.is_configured():
        console.print(Panel(
            "[yellow]SLACK_BOT_TOKEN and SLACK_APP_TOKEN are not set.[/yellow]\n\n"
            "To enable the Slack bot:\n"
            "  1. Create a Slack App at https://api.slack.com/apps\n"
            "  2. Enable Socket Mode\n"
            "  3. Add Bot Token Scopes: app_mentions:read, chat:write, commands\n"
            "  4. Copy tokens to .env:\n"
            "     SLACK_BOT_TOKEN=xoxb-...\n"
            "     SLACK_APP_TOKEN=xapp-...",
            title="[bold]Slack Bot Setup Required[/bold]",
            border_style="yellow",
        ))
        return
    console.print(Panel(
        f"[bold cyan]Cloud Ops Slack Bot[/bold cyan]\n"
        f"[dim]Phase {PHASE} — Socket Mode[/dim]\n\n"
        f"[dim]Press Ctrl+C to stop.[/dim]",
        border_style="cyan",
    ))
    slack_bot.start()  # blocking


def start_listener() -> None:
    from agents.event_listener import EventListener
    from config import EVENT_LISTENER_PORT, PHASE
    console.print(Panel(
        f"[bold cyan]Cloud Ops Webhook Server[/bold cyan]\n"
        f"[dim]Phase {PHASE} — listening for GCP Monitoring alerts[/dim]\n\n"
        f"  POST http://0.0.0.0:{EVENT_LISTENER_PORT}/webhook\n"
        f"  GET  http://0.0.0.0:{EVENT_LISTENER_PORT}/health\n\n"
        f"[dim]Press Ctrl+C to stop.[/dim]",
        border_style="cyan",
    ))
    listener = EventListener(port=EVENT_LISTENER_PORT)
    listener.start()  # blocking


def scaffold_module(api: str, domain: str | None) -> None:
    from tools.scaffolder import generate_stub, _suggest_domain
    suggested = domain or _suggest_domain(api)
    try:
        path = generate_stub(api, domain)
    except FileExistsError as e:
        console.print(f"[yellow]{e}[/yellow]")
        return
    console.print(f"\n[green]✓ Stub created:[/green] {path}\n")
    console.print(Panel(
        f"[bold]Next steps:[/bold]\n\n"
        f"  1. Fill in the tool function(s) in [cyan]{path.name}[/cyan]\n"
        f"     API reference: [dim]https://developers.google.com/discovery/v1/reference/apis/list[/dim]\n\n"
        f"  2. Verify detection:  [cyan]python main.py --list-services[/cyan]\n\n"
        f"  3. Test end-to-end:   [cyan]python main.py --agent {suggested}[/cyan]",
        border_style="cyan",
    ))


def run_finops() -> None:
    from finops.engine import FinOpsEngine
    FinOpsEngine().run(inject_findings=False)


def run_slo() -> None:
    from slo.manager import SLOManager
    from rich.table import Table
    manager = SLOManager()
    results = manager.evaluate_all(inject_findings=False)
    if not results:
        console.print("[dim]No SLO definitions found. Add entries to slo/definitions.yaml[/dim]")
        return
    table = Table(title="SLO Evaluation", show_lines=True)
    table.add_column("SLO", style="cyan", width=30)
    table.add_column("Target", justify="right", width=8)
    table.add_column("Error Rate", justify="right", width=12)
    table.add_column("Burn Rate", justify="right", width=10)
    table.add_column("Budget Left", justify="right", width=12)
    table.add_column("Status", width=10)
    for r in results:
        if not r.data_available:
            status = "[dim]no data[/dim]"
        elif r.alert:
            status = "[red]AT RISK[/red]"
        elif r.burn_rate > 1.0:
            status = "[yellow]elevated[/yellow]"
        else:
            status = "[green]healthy[/green]"
        table.add_row(
            r.name[:29],
            f"{r.target:.1%}",
            f"{r.current_error_rate:.4%}" if r.data_available else "—",
            f"{r.burn_rate:.2f}x" if r.data_available else "—",
            f"{r.budget_remaining_pct:.1f}%" if r.data_available else "—",
            status,
        )
    console.print(table)


def run_iac_drift() -> None:
    from iac.drift_detector import TerraformDriftDetector
    from rich.table import Table
    detector = TerraformDriftDetector()
    report = detector.detect()
    if not report.drift_items:
        console.print("[green]No IaC drift detected.[/green]")
        return
    table = Table(title=f"IaC Drift Report ({report.run_id})", show_lines=True)
    table.add_column("Resource Type", style="cyan", width=28)
    table.add_column("Name", width=25)
    table.add_column("Drift Type", width=14)
    table.add_column("Detail", width=45)
    table.add_column("Suggested Fix", width=45)
    for item in report.drift_items:
        color = "red" if item.drift_type == "shadow" else "yellow" if item.drift_type == "stale" else "dim"
        table.add_row(
            item.resource_type, item.resource_name,
            f"[{color}]{item.drift_type}[/{color}]",
            item.detail[:44], item.suggested_fix[:44],
        )
    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] "
        f"shadow={report.shadow_count}  stale={report.stale_count}  "
        f"config_drift={report.config_drift_count}"
    )


def run_rca() -> None:
    from agents.rca_engine import RCAEngine
    from memory.store import store
    findings = store.critical_and_high()
    if not findings:
        console.print("[dim]No CRITICAL/HIGH findings in store. Run a full cycle first.[/dim]")
        return
    engine = RCAEngine()
    result = engine.analyse(findings)
    if not result:
        console.print("[dim]RCA: no critical/high findings to analyse.[/dim]")
        return
    console.print(Panel(
        f"[bold]Root Cause:[/bold] {result.root_cause}\n\n"
        f"[bold]Causal Chain:[/bold] {result.causal_chain}\n\n"
        f"[bold]Recommended Fix:[/bold] {result.recommended_fix}\n\n"
        f"[bold]Confidence:[/bold] {result.confidence}\n"
        f"[bold]Supporting Evidence:[/bold]\n"
        + "\n".join(f"  • {e}" for e in result.supporting_evidence),
        title="[bold magenta]Root Cause Analysis[/bold magenta]",
        border_style="magenta",
    ))


def run_postmortem(run_id: str) -> None:
    from postmortems.generator import PostMortemGenerator
    console.print(f"[dim]Generating post-mortem for run: {run_id}...[/dim]")
    gen = PostMortemGenerator()
    path = gen.generate(run_id=run_id)
    console.print(f"\n[green]✓ Post-mortem saved:[/green] {path}")


def show_tenants() -> None:
    from tenants.manager import tenant_manager
    from rich.table import Table
    s = tenant_manager.summary()
    table = Table(title=f"Multi-Tenant Configuration ({s['config_file']})", show_lines=True)
    table.add_column("Team ID", style="cyan", width=12)
    table.add_column("Name", width=22)
    table.add_column("Domains", width=35)
    table.add_column("Slack Channel", width=20)
    table.add_column("Min Severity", width=14)
    for team in tenant_manager.all_teams():
        table.add_row(
            team.id, team.name,
            ", ".join(team.domains) or "[dim]all[/dim]",
            team.slack_channel or "[dim]—[/dim]",
            team.severity_filter,
        )
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cloud Ops Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--trigger", default="scheduled",
                        help="Run trigger label (scheduled, alert, manual)")
    parser.add_argument("--agent", default=None,
                        help="Run a single agent domain (infra, cost, security, incident, deployment, data)")
    parser.add_argument("--phase", type=int, default=None,
                        help="Override phase (1=observe, 2=supervised, 3=autonomous, 4=predictive)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Phase 2/3: simulate actions without modifying GCP")
    parser.add_argument("--confirm-destructive", action="store_true",
                        help="Phase 2: allow irreversible actions to be proposed")
    parser.add_argument("--list-services", action="store_true",
                        help="Show all registered GCP services and their enabled status")
    parser.add_argument("--scaffold", default=None, metavar="API",
                        help="Generate a stub module for a new GCP service API")
    parser.add_argument("--domain", default=None,
                        help="Agent domain for the scaffolded module")
    parser.add_argument("--history", action="store_true",
                        help="Phase 3: show cross-run finding and action history summary")
    parser.add_argument("--policy", action="store_true",
                        help="Phase 3: show loaded policy rules")
    parser.add_argument("--listen", action="store_true",
                        help="Phase 3: start webhook server for GCP Monitoring alert triggers")
    parser.add_argument("--compliance", action="store_true",
                        help="Phase 4: run CIS GCP compliance scan only")
    parser.add_argument("--predict", action="store_true",
                        help="Phase 4: run predictive trend forecast only")
    parser.add_argument("--runbooks", action="store_true",
                        help="Phase 4: list loaded runbooks")
    parser.add_argument("--list-clouds", action="store_true",
                        help="Phase 4: show all registered services across GCP and AWS")
    parser.add_argument("--slack", action="store_true",
                        help="Phase 4: start two-way Slack ChatOps bot")
    # Phase 5
    parser.add_argument("--finops", action="store_true",
                        help="Phase 5: run FinOps analysis only")
    parser.add_argument("--slo", action="store_true",
                        help="Phase 5: evaluate SLOs only")
    parser.add_argument("--iac-drift", action="store_true",
                        help="Phase 5: run IaC drift detection only")
    parser.add_argument("--rca", action="store_true",
                        help="Phase 5: run root cause analysis on latest findings")
    parser.add_argument("--postmortem", default=None, metavar="RUN_ID",
                        help="Phase 5: generate post-mortem for a completed run ID")
    parser.add_argument("--tenants", action="store_true",
                        help="Phase 5: show multi-tenant team configuration")
    # Sandbox
    parser.add_argument("--sandbox-provision", action="store_true",
                        help="Sandbox: provision intentionally misconfigured demo resources in GCP")
    parser.add_argument("--sandbox-teardown", action="store_true",
                        help="Sandbox: delete all demo resources created by --sandbox-provision")
    parser.add_argument("--sandbox-demo", action="store_true",
                        help="Sandbox: run the full guided interactive demo (provisions if needed)")
    parser.add_argument("--skip-vm", action="store_true",
                        help="Sandbox: skip VM creation during provisioning (faster, cost-free)")
    args = parser.parse_args()

    # Apply CLI overrides before any config import
    _apply_cli_overrides(args)

    if not validate_config():
        sys.exit(1)

    if args.scaffold:
        scaffold_module(args.scaffold, args.domain)
        return

    if args.list_services:
        list_services()
        return

    if args.history:
        show_history()
        return

    if args.policy:
        show_policy()
        return

    if args.listen:
        check_coverage()
        start_listener()
        return

    if args.compliance:
        run_compliance()
        return

    if args.predict:
        run_predict()
        return

    if args.runbooks:
        list_runbooks()
        return

    if args.list_clouds:
        list_clouds()
        return

    if args.slack:
        start_slack_bot()
        return

    # Phase 5 utilities
    if args.finops:
        run_finops()
        return

    if args.slo:
        run_slo()
        return

    if args.iac_drift:
        run_iac_drift()
        return

    if args.rca:
        run_rca()
        return

    if args.postmortem:
        run_postmortem(args.postmortem)
        return

    if args.tenants:
        show_tenants()
        return

    if args.sandbox_provision:
        from sandbox.provision import provision_all
        provision_all(skip_vm=args.skip_vm)
        return

    if args.sandbox_teardown:
        from sandbox.teardown import teardown_all
        teardown_all()
        return

    if args.sandbox_demo:
        from sandbox.demo import run_demo
        run_demo()
        return

    check_coverage()

    if args.agent:
        run_single_agent(args.agent)
    else:
        run_full_cycle(trigger=args.trigger)


if __name__ == "__main__":
    main()
