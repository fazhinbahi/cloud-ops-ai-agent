"""
agents/supervisor.py — Supervisor Agent (Phase 1 → 5).

Phase 1: observe → report
Phase 2: observe → report → propose → human gate → execute → audit
Phase 3: observe → report → propose → policy gate → execute → verify → rollback → history
Phase 4: predict → compliance → observe → report → propose → policy gate → execute
         → verify → rollback → history → runbooks → Slack notification
Phase 5: FinOps → SLO → IaC drift → RCA → multi-tenant routing → post-mortem

Phase 2 tail: PHASE >= 2
Phase 3 tail: PHASE >= 3
Phase 4 tail: PHASE >= 4
Phase 5 tail: PHASE >= 5
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import anthropic

from config import (
    SUPERVISOR_MODEL, ANTHROPIC_API_KEY, PHASE, OBSERVE_ONLY, DRY_RUN,
    AUTO_ROLLBACK, VERIFY_AFTER_EXECUTE,
)
from memory.store import store, Finding
from memory.actions import actions_store
from memory.history import history_db
from tools.reporting_tools import (
    print_findings_table,
    print_agent_report,
    save_report_to_disk,
    post_to_slack,
    console,
)
from rich.panel import Panel
from rich.table import Table


# ── Domain → Agent class mapping ──────────────────────────────────────────────

def _build_domain_map() -> dict:
    from agents.infra_agent import InfraAgent
    from agents.cost_agent import CostAgent
    from agents.security_agent import SecurityAgent
    from agents.incident_agent import IncidentAgent
    from agents.deployment_agent import DeploymentAgent
    from agents.data_agent import DataAgent

    return {
        "infra":      InfraAgent,
        "cost":       CostAgent,
        "security":   SecurityAgent,
        "incident":   IncidentAgent,
        "deployment": DeploymentAgent,
        "data":       DataAgent,
    }


class SupervisorAgent:
    """Orchestrates specialist agents and (in Phase 2) the full action lifecycle."""

    def __init__(self):
        self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    # ── Public entry points ────────────────────────────────────────────────────

    def run_scoped(self, domain: str, trigger: str = "alert") -> dict:
        """
        Run a single-domain agent cycle (used by event_listener for targeted alerts).
        Findings are added to the shared store and persisted to history.
        If PHASE >= 2, immediately runs the action cycle for any critical/high findings.
        """
        domain_map = _build_domain_map()
        AgentClass = domain_map.get(domain)
        if not AgentClass:
            console.print(f"[red]Unknown domain for scoped run: {domain}[/red]")
            return {"run_id": self._run_id, "error": f"unknown domain: {domain}"}

        agent = AgentClass()
        findings = agent.run()
        print_agent_report(agent.name, findings)
        store.add_many(findings)

        for f in findings:
            history_db.record_finding(f, self._run_id)

        result: dict = {
            "run_id": self._run_id,
            "trigger": trigger,
            "domain": domain,
            "total_findings": len(findings),
        }

        if PHASE >= 2:
            actionable = [f for f in findings if f.severity in ("critical", "high")]
            if actionable:
                actions_result = self._run_action_cycle(actionable)
                result.update(actions_result)

        return result

    def run(self, trigger: str = "scheduled") -> dict:
        phase_label = f"Phase {PHASE}" + (
            " — Observe Only" if PHASE < 2
            else " — Supervised Action" if PHASE == 2
            else " — Autonomous"
        )
        dry_label = " [DRY RUN]" if DRY_RUN else ""

        console.print(Panel(
            f"[bold cyan]Cloud Ops Multi-Agent System[/bold cyan]\n"
            f"[dim]{phase_label}{dry_label}[/dim]\n"
            f"[dim]Trigger: {trigger} | Run ID: {self._run_id}[/dim]",
            border_style="cyan",
        ))

        if PHASE < 2:
            console.print("[yellow]⚠  OBSERVE-ONLY MODE: No actions will be taken.[/yellow]\n")

        # ── Phase 5: FinOps analysis ──────────────────────────────────────────
        if PHASE >= 5:
            self._run_finops()

        # ── Phase 5: SLO evaluation ───────────────────────────────────────────
        if PHASE >= 5:
            self._run_slo()

        # ── Phase 5: IaC drift detection ─────────────────────────────────────
        if PHASE >= 5:
            self._run_iac_drift()

        # ── Phase 4: Predictive forecast ──────────────────────────────────────
        predictions = []
        if PHASE >= 4:
            predictions = self._run_predictor()

        # ── Phase 4: Compliance scan ──────────────────────────────────────────
        if PHASE >= 4:
            self._run_compliance()

        # ── Phase 1: Observe cycle ────────────────────────────────────────────
        all_findings = self._run_observe_cycle()

        print_findings_table(all_findings)
        summary = self._synthesize(all_findings, trigger, predictions)
        report_path = save_report_to_disk(store, run_id=self._run_id)

        post_to_slack(all_findings)

        console.print(Panel(
            summary,
            title="[bold]EXECUTIVE SUMMARY[/bold]",
            border_style="green",
        ))

        result = {
            "run_id": self._run_id,
            "trigger": trigger,
            "phase": PHASE,
            "total_findings": len(all_findings),
            "predictions": len(predictions),
            "summary": store.summary(),
            "report_path": str(report_path),
        }

        # ── Phase 2+: Propose → Approve → Execute ────────────────────────────
        if PHASE >= 2:
            actions_result = self._run_action_cycle(all_findings)
            result.update(actions_result)

        # ── Phase 4: Run matching runbooks ────────────────────────────────────
        if PHASE >= 4:
            rb_result = self._run_runbooks(all_findings)
            result.update(rb_result)

        # ── Phase 5: RCA on critical/high findings ────────────────────────────
        if PHASE >= 5:
            rca_result = self._run_rca(all_findings)
            result["rca"] = rca_result.to_dict() if rca_result else None

        # ── Phase 5: Multi-tenant routing ─────────────────────────────────────
        if PHASE >= 5:
            self._run_tenant_routing(all_findings)

        # ── Phase 5: Post-mortem generation ───────────────────────────────────
        if PHASE >= 5 and result.get("total_findings", 0) > 0:
            pm_path = self._generate_postmortem(
                all_findings,
                rca_result=rca_result if PHASE >= 5 else None,
            )
            result["postmortem_path"] = str(pm_path) if pm_path else None

        return result

    # ── Phase 1: Observe ──────────────────────────────────────────────────────

    def _run_observe_cycle(self) -> list[Finding]:
        from tools.registry import get_active_domains, list_all_services

        domain_map = _build_domain_map()
        active_domains = get_active_domains()
        active_agents = [
            domain_map[d] for d in active_domains if d in domain_map
        ]

        if not active_agents:
            console.print("[red]No enabled GCP services found.[/red]")
            return []

        enabled_count = sum(1 for s in list_all_services() if s["enabled"])
        console.print(
            f"[dim]Monitoring {enabled_count} enabled services across "
            f"{len(active_agents)} agent domains.[/dim]\n"
        )

        all_findings: list[Finding] = []
        for AgentClass in active_agents:
            agent = AgentClass()
            findings = agent.run()
            all_findings.extend(findings)
            print_agent_report(agent.name, findings)

        # Phase 3: persist every finding to cross-run history
        if PHASE >= 3:
            for f in all_findings:
                history_db.record_finding(f, self._run_id)

        console.print("\n")
        return all_findings

    # ── Phase 2 / 3: Propose → Approve/Auto → Execute → Verify → Rollback ────

    def _run_action_cycle(self, all_findings: list[Finding]) -> dict:
        from agents.proposal_engine import ProposalEngine
        from agents.approval_gate import ApprovalGate
        from agents.policy_engine import PolicyEngine
        from agents.verifier import Verifier
        from execution.engine import ExecutionEngine
        from execution.rollback import RollbackEngine
        from audit.log import AuditLogger

        audit = AuditLogger(run_id=self._run_id)
        audit.write_session_start(phase=PHASE, trigger="supervisor")

        # 1. Propose actions for critical + high findings
        actionable = store.critical_and_high()
        if not actionable:
            console.print("[green]No CRITICAL/HIGH findings — nothing to remediate.[/green]")
            audit.write_session_end({"proposed": 0, "approved": 0, "succeeded": 0})
            return {"proposed": 0, "approved": 0, "succeeded": 0, "audit_path": str(audit.path)}

        console.print(Panel(
            f"[bold]Generating action proposals for {len(actionable)} critical/high finding(s)...[/bold]",
            border_style="yellow",
        ))

        engine = ProposalEngine()
        proposed = engine.propose(actionable, run_id=self._run_id)
        actions_store.add_many(proposed)

        for a in proposed:
            audit.write(a, "proposed")

        if not proposed:
            console.print("[dim]No actionable proposals generated.[/dim]")
            audit.write_session_end({"proposed": 0, "approved": 0, "succeeded": 0})
            return {"proposed": 0, "approved": 0, "succeeded": 0, "audit_path": str(audit.path)}

        # 2. Phase 3: policy-based auto-approval; Phase 2: human gate for all
        auto_approved = 0
        if PHASE >= 3:
            policy = PolicyEngine()
            self._print_policy_summary(policy)
            for action in proposed:
                decision = policy.evaluate(action)
                reason = policy.explain(action)
                if decision == "auto_approve":
                    action.status = "approved"
                    action.decided_by = "policy"
                    actions_store.update(action)
                    audit.write(action, "auto_approved", detail=reason)
                    auto_approved += 1
                elif decision == "auto_reject":
                    action.status = "rejected"
                    action.decided_by = "policy"
                    actions_store.update(action)
                    audit.write(action, "auto_rejected", detail=reason)

            # Show the gate only for actions that still need human input
            need_human = [a for a in proposed if a.status == "proposed"]
            if need_human:
                console.print(
                    f"[dim]{auto_approved} action(s) auto-approved by policy. "
                    f"{len(need_human)} require human review.[/dim]\n"
                )
                gate = ApprovalGate(audit_logger=audit)
                gate.run(need_human, store=actions_store)
            else:
                console.print(
                    f"[green]All {auto_approved} action(s) auto-approved by policy.[/green]\n"
                )
        else:
            # Phase 2: every action goes to the human gate
            gate = ApprovalGate(audit_logger=audit)
            gate.run(proposed, store=actions_store)

        approved_count = sum(1 for a in proposed if a.status == "approved")
        if approved_count == 0:
            console.print("[dim]No actions approved. Nothing executed.[/dim]")
            actions_path = actions_store.flush_to_disk(run_id=self._run_id)
            audit.write_session_end({"proposed": len(proposed), "approved": 0, "succeeded": 0})
            return {
                "proposed": len(proposed),
                "approved": 0,
                "succeeded": 0,
                "actions_path": str(actions_path),
                "audit_path": str(audit.path),
            }

        # 3. Execute approved actions
        console.print(Panel(
            f"[bold]Executing {approved_count} approved action(s)...[/bold]"
            + (" [DRY RUN — no GCP changes]" if DRY_RUN else ""),
            border_style="cyan",
        ))

        exec_engine = ExecutionEngine(audit_logger=audit, dry_run=DRY_RUN)
        results = exec_engine.execute(proposed, store=actions_store)

        # 4. Phase 3: verify + auto-rollback
        rolled_back = 0
        if PHASE >= 3 and VERIFY_AFTER_EXECUTE:
            verifier = Verifier()
            rollback_engine = RollbackEngine(audit_logger=audit, dry_run=DRY_RUN)
            results, rolled_back = self._verify_and_rollback(
                results, verifier, rollback_engine, actions_store
            )

        # 5. Phase 3: persist actions to cross-run history
        if PHASE >= 3:
            for a in results:
                history_db.record_action(a)

        # 6. Print execution results
        self._print_execution_results(results)

        # 7. Persist
        actions_path = actions_store.flush_to_disk(run_id=self._run_id)
        succeeded = sum(1 for a in results if a.status == "succeeded")
        failed = sum(1 for a in results if a.status == "failed")

        audit.write_session_end({
            "proposed": len(proposed),
            "approved": approved_count,
            "auto_approved": auto_approved,
            "succeeded": succeeded,
            "failed": failed,
            "rolled_back": rolled_back,
        })

        console.print(f"\n[dim]Audit log: {audit.path}[/dim]")
        console.print(f"[dim]Actions report: {actions_path}[/dim]")

        # Phase 3: show recurring patterns if any
        if PHASE >= 3:
            self._print_patterns()

        return {
            "proposed": len(proposed),
            "approved": approved_count,
            "auto_approved": auto_approved,
            "succeeded": succeeded,
            "failed": failed,
            "rolled_back": rolled_back,
            "actions_path": str(actions_path),
            "audit_path": str(audit.path),
        }

    # ── Phase 3 helpers ───────────────────────────────────────────────────────

    def _verify_and_rollback(
        self,
        results: list,
        verifier,
        rollback_engine,
        actions_store,
    ) -> tuple[list, int]:
        """Verify each succeeded action and roll back if verification fails."""
        rolled_back = 0
        console.print("\n[dim]Phase 3: verifying execution results...[/dim]")

        for action in results:
            if action.status != "succeeded":
                continue

            vr = verifier.verify(action)

            if vr.unverifiable:
                console.print(f"  [dim]⊘ {action.title}: {vr.detail}[/dim]")
                continue

            if vr.resolved:
                console.print(f"  [green]✓ {action.title}: verified — {vr.detail}[/green]")
            else:
                console.print(f"  [red]✗ {action.title}: verification FAILED — {vr.detail}[/red]")
                if AUTO_ROLLBACK and rollback_engine.can_rollback(action.action_type):
                    console.print(f"    [yellow]→ Auto-rolling back...[/yellow]")
                    rb_result = rollback_engine.rollback(action, store=actions_store)
                    if rb_result["success"]:
                        console.print(f"    [green]✓ Rollback succeeded.[/green]")
                        rolled_back += 1
                    else:
                        console.print(f"    [red]✗ Rollback failed: {rb_result['message']}[/red]")
                else:
                    console.print(f"    [yellow]⚠ Manual rollback required: {action.rollback_instructions}[/yellow]")

        return results, rolled_back

    def _print_policy_summary(self, policy) -> None:
        s = policy.summary()
        console.print(
            f"[dim]Phase 3 policy: {s['rules_loaded']} rules loaded from "
            f"{s['policy_file']}. Default: {s['default_decision']}.[/dim]\n"
        )

    def _print_patterns(self) -> None:
        patterns = history_db.recurring_findings()
        if not patterns:
            return
        table = Table(title="Recurring Findings (Phase 3 Pattern Detection)", show_lines=True)
        table.add_column("Resource", style="cyan", width=30)
        table.add_column("Check Type", style="yellow", width=20)
        table.add_column("Agent", width=12)
        table.add_column("Occurrences", justify="right", width=12)
        table.add_column("Last Seen", width=25)
        for p in patterns:
            table.add_row(
                p["resource"], p["check_type"], p["agent"],
                str(p["occurrences"]), p["last_seen"][:19],
            )
        console.print("\n", table)
        console.print(
            "[yellow]⚠  Recurring patterns detected. "
            "Consider investigating root cause or adjusting policy.[/yellow]\n"
        )

    def _print_execution_results(self, results: list) -> None:
        if not results:
            return
        table = Table(title="Execution Results", show_lines=True)
        table.add_column("Action", width=40)
        table.add_column("Resource", width=25)
        table.add_column("Status", width=12)
        table.add_column("Outcome", width=40)

        for a in results:
            status_str = (
                "[green]succeeded[/green]" if a.status == "succeeded"
                else "[red]failed[/red]"
            )
            table.add_row(a.title, a.resource, status_str, a.outcome[:60])

        console.print("\n", table)

        # Print rollback reference for succeeded actions
        succeeded = [a for a in results if a.status == "succeeded"]
        if succeeded:
            console.print("\n[bold]Rollback Reference:[/bold]")
            for a in succeeded:
                console.print(f"  [cyan]{a.title}[/cyan]: {a.rollback_instructions}")

    # ── Phase 4 helpers ───────────────────────────────────────────────────────

    def _run_predictor(self) -> list:
        from agents.predictor import Predictor
        from rich.table import Table
        predictor = Predictor()
        predictions = predictor.run()
        if predictions:
            table = Table(title="Phase 4 Predictive Forecasts", show_lines=True)
            table.add_column("Resource", style="cyan", width=28)
            table.add_column("Prediction", width=40)
            table.add_column("Confidence", width=10)
            table.add_column("Recommended Action", width=35)
            for p in predictions:
                conf_color = "green" if p.confidence == "high" else "yellow" if p.confidence == "medium" else "dim"
                table.add_row(
                    p.resource, p.prediction[:39],
                    f"[{conf_color}]{p.confidence}[/{conf_color}]",
                    p.recommended_action[:34],
                )
            console.print(table)
        else:
            console.print("[dim]Phase 4 Predictor: no forecasts generated.[/dim]")
        return predictions

    def _run_compliance(self) -> None:
        from agents.compliance_agent import ComplianceAgent
        agent = ComplianceAgent()
        agent.run()

    def _run_runbooks(self, findings: list[Finding]) -> dict:
        from runbooks.engine import RunbookEngine
        from audit.log import AuditLogger
        from integrations.slack_bot import slack_bot

        audit = AuditLogger(run_id=self._run_id)
        rb_engine = RunbookEngine(
            audit_logger=audit,
            dry_run=DRY_RUN,
            slack_notifier=slack_bot if slack_bot.is_configured() else None,
        )

        matches = rb_engine.find_matching(findings)
        if not matches:
            return {"runbooks_triggered": 0}

        console.print(Panel(
            f"[bold]Phase 4: Triggering {len(matches)} runbook(s)...[/bold]",
            border_style="magenta",
        ))

        rb_results = []
        for runbook, finding in matches:
            console.print(f"  [magenta]→ {runbook['name']}[/magenta] for finding: [cyan]{finding.title}[/cyan]")
            result = rb_engine.run(runbook, finding, store=actions_store)
            rb_results.append(result)
            status_color = "green" if result.succeeded() else "yellow"
            console.print(
                f"    [{status_color}]{result.final_status}[/{status_color}] "
                f"— {len(result.steps_executed)} step(s) executed."
            )

        return {
            "runbooks_triggered": len(rb_results),
            "runbooks_completed": sum(1 for r in rb_results if r.succeeded()),
        }

    # ── Phase 5 helpers ───────────────────────────────────────────────────────

    def _run_finops(self) -> None:
        from finops.engine import FinOpsEngine
        from rich.console import Console
        try:
            engine = FinOpsEngine()
            engine.run(inject_findings=True)
        except Exception as exc:
            console.print(f"[yellow]Phase 5 FinOps: {exc}[/yellow]")

    def _run_slo(self) -> None:
        from slo.manager import SLOManager
        try:
            manager = SLOManager()
            results = manager.evaluate_all(inject_findings=True)
            alerts = [r for r in results if r.alert and r.data_available]
            if alerts:
                console.print(f"  [red]SLO: {len(alerts)} SLO(s) at risk.[/red]")
            else:
                console.print(f"  [green]SLO: {len(results)} SLO(s) evaluated — all healthy.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Phase 5 SLO: {exc}[/yellow]")

    def _run_iac_drift(self) -> None:
        from iac.drift_detector import TerraformDriftDetector
        from config import IAC_STATE_FILE
        if not IAC_STATE_FILE:
            console.print("[dim]Phase 5 IaC Drift: IAC_STATE_FILE not set — skipping.[/dim]")
            return
        try:
            detector = TerraformDriftDetector()
            report = detector.detect()
            total = len(report.drift_items)
            if total:
                console.print(
                    f"  [yellow]IaC Drift: {total} drift item(s) detected "
                    f"(shadow={report.shadow_count}, stale={report.stale_count}, "
                    f"config={report.config_drift_count}).[/yellow]"
                )
                # Inject as findings
                from memory.store import store, Finding
                for item in report.drift_items:
                    sev = "high" if item.drift_type == "shadow" else "medium"
                    store.add(Finding(
                        agent="security",
                        severity=sev,
                        title=f"IaC drift [{item.drift_type}]: {item.resource_name}",
                        detail=item.detail + (
                            f"\nSuggested fix: {item.suggested_fix}" if item.suggested_fix else ""
                        ),
                        resource=item.resource_name,
                    ))
            else:
                console.print("[green]  IaC Drift: no drift detected.[/green]")
        except Exception as exc:
            console.print(f"[yellow]Phase 5 IaC Drift: {exc}[/yellow]")

    def _run_rca(self, findings: list) -> object | None:
        from agents.rca_engine import RCAEngine
        try:
            engine = RCAEngine()
            result = engine.analyse(findings)
            if result:
                console.print(Panel(
                    f"[bold]Root Cause:[/bold] {result.root_cause}\n\n"
                    f"[bold]Causal Chain:[/bold] {result.causal_chain}\n\n"
                    f"[bold]Recommended Fix:[/bold] {result.recommended_fix}\n"
                    f"[dim]Confidence: {result.confidence} | "
                    f"Timeline events: {len(result.timeline)}[/dim]",
                    title="[bold magenta]Phase 5 Root Cause Analysis[/bold magenta]",
                    border_style="magenta",
                ))
            return result
        except Exception as exc:
            console.print(f"[yellow]Phase 5 RCA: {exc}[/yellow]")
            return None

    def _run_tenant_routing(self, findings: list) -> None:
        from tenants.manager import tenant_manager
        try:
            routing = tenant_manager.route_findings_by_team(findings)
            if routing:
                console.print("\n[dim]Phase 5 Multi-Tenant Routing:[/dim]")
                for team_id, team_findings in routing.items():
                    team = tenant_manager.get_team(team_id)
                    name = team.name if team else team_id
                    channel = tenant_manager.get_slack_channel(team_id)
                    console.print(
                        f"  [cyan]{name}[/cyan] — {len(team_findings)} finding(s)"
                        + (f" → [dim]{channel}[/dim]" if channel else "")
                    )
        except Exception as exc:
            console.print(f"[yellow]Phase 5 Tenant routing: {exc}[/yellow]")

    def _generate_postmortem(self, findings: list, rca_result=None) -> object | None:
        from postmortems.generator import PostMortemGenerator
        try:
            gen = PostMortemGenerator()
            path = gen.generate(
                run_id=self._run_id,
                rca_result=rca_result,
                findings=findings,
            )
            console.print(f"\n[dim]Phase 5 Post-Mortem: {path}[/dim]")
            return path
        except Exception as exc:
            console.print(f"[yellow]Phase 5 Post-Mortem generation: {exc}[/yellow]")
            return None

    # ── Synthesis ─────────────────────────────────────────────────────────────

    def _synthesize(self, findings: list[Finding], trigger: str, predictions: list | None = None) -> str:
        if not findings and not predictions:
            return "No issues found. Environment looks healthy."

        findings_json = json.dumps(
            [f.model_dump() for f in findings], indent=2, default=str
        )

        predictions_section = ""
        if predictions:
            predictions_json = json.dumps(
                [p.to_dict() for p in predictions], indent=2, default=str
            )
            predictions_section = f"\n\nPREDICTIVE FORECASTS (Phase 4):\n{predictions_json}"

        response = self._client.messages.create(
            model=SUPERVISOR_MODEL,
            max_tokens=2048,
            thinking={"type": "adaptive"},
            system="""You are the Supervisor of a multi-agent cloud operations system (GCP + AWS).
Produce a concise executive summary for the on-call engineer.

Structure:
1. Overall health: Healthy / At Risk / Degraded / Critical
2. Top 3-5 most important issues (grouped by resource where possible)
3. "Predicted Issues" section — if predictive forecasts are provided, summarise the top 2
4. "Immediate Actions Needed" section

Plain English. No markdown headers. Under 350 words.
""",
            messages=[{"role": "user", "content": f"""
Trigger: {trigger}
Total findings: {len(findings)}
By severity: {json.dumps(store.summary()["by_severity"])}

{findings_json}{predictions_section}

Produce the executive summary.
"""}],
        )

        return next(
            (b.text for b in response.content if b.type == "text"),
            "Summary unavailable.",
        )
