"""
agents/compliance_agent.py — Phase 4 Compliance Agent.

Runs all loaded compliance framework checks (CIS GCP, and any custom
frameworks in compliance/frameworks/) and converts failures into
Finding objects that flow through the standard observe → report → action pipeline.

Compliance failures that have auto_fix set will be auto-proposed in
Phase 3 (policy engine evaluates them like any other finding).
"""
from __future__ import annotations

from compliance.engine import ComplianceEngine, ComplianceResult
from memory.store import Finding, store
from tools.reporting_tools import console
from rich.table import Table


class ComplianceAgent:
    """
    Specialist agent for continuous compliance enforcement.

    Runs all configured compliance frameworks and emits findings for
    every failed control. Passed controls are silently ignored.
    """

    name = "security"   # findings attributed to security domain

    def run(self) -> list[Finding]:
        console.print("\n[COMPLIANCE AGENT] Running framework checks...")

        engine = ComplianceEngine()
        results = engine.run()
        summary = engine.summary(results)

        self._print_compliance_table(results, summary)

        failures = [r for r in results if not r.passed]
        findings = [self._to_finding(r) for r in failures]
        store.add_many(findings)

        console.print(
            f"[COMPLIANCE AGENT] Score: [bold]{summary['compliance_score']}%[/bold] "
            f"({summary['passed']}/{summary['total_controls']} controls passed). "
            f"{len(findings)} finding(s) raised.\n"
        )
        return findings

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _to_finding(self, result: ComplianceResult) -> Finding:
        return Finding(
            agent=self.name,
            severity=result.severity,
            title=f"[{result.control_id}] {result.title}",
            detail=(
                f"{result.detail}\n\n"
                f"Framework: {result.framework}\n"
                f"Section: {result.section}\n"
                f"Remediation: {result.remediation}"
            ),
            resource=", ".join(result.affected_resources[:5]) or "project-level",
            region="",
            tags={
                "compliance_framework": result.framework,
                "control_id": result.control_id,
                "auto_fix": result.auto_fix or "",
            },
        )

    def _print_compliance_table(
        self,
        results: list[ComplianceResult],
        summary: dict,
    ) -> None:
        score = summary["compliance_score"]
        score_color = "green" if score >= 80 else "yellow" if score >= 60 else "red"

        table = Table(
            title=f"Compliance Report — Score: [{score_color}]{score}%[/{score_color}]",
            show_lines=True,
        )
        table.add_column("ID", style="dim", width=6)
        table.add_column("Control", width=45)
        table.add_column("Severity", width=10)
        table.add_column("Status", width=8)
        table.add_column("Detail", width=50)

        for r in sorted(results, key=lambda x: (x.passed, x.severity)):
            status = "[green]PASS[/green]" if r.passed else "[red]FAIL[/red]"
            sev_color = {
                "critical": "red", "high": "yellow",
                "medium": "cyan", "low": "dim",
            }.get(r.severity, "white")
            table.add_row(
                r.control_id,
                r.title[:44],
                f"[{sev_color}]{r.severity}[/{sev_color}]",
                status,
                r.detail[:49],
            )
        console.print(table)
