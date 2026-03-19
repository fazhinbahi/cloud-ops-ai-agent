"""
agents/approval_gate.py — Interactive human approval gate for Phase 2 actions.

Presents each proposed action one at a time with full context.
The human types [y]es, [n]o, [s]kip all, or [q]uit.

Irreversible actions are blocked unless CONFIRM_DESTRUCTIVE=True.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from memory.actions import Action, ActionsStore
from audit.log import AuditLogger
from config import CONFIRM_DESTRUCTIVE

console = Console()

# Severity → color for the action panel border
_CATEGORY_COLOR = {
    "security":    "red",
    "cost":        "yellow",
    "reliability": "blue",
    "compliance":  "magenta",
}

_REVERSIBILITY_ICON = {
    "reversible":       "[green]✓ Reversible[/green]",
    "semi-reversible":  "[yellow]~ Semi-reversible[/yellow]",
    "irreversible":     "[red]✗ IRREVERSIBLE[/red]",
}


class ApprovalGate:
    """
    Interactive approval loop.

    Returns the input list with status updated:
      approved  → human said [y]
      rejected  → human said [n]
      skipped   → human chose [s] (skip all remaining)
    """

    def __init__(self, audit_logger: AuditLogger):
        self._audit = audit_logger

    def run(self, actions: list[Action], store: ActionsStore) -> list[Action]:
        if not actions:
            console.print("[dim]No actions proposed.[/dim]")
            return actions

        self._print_summary_table(actions)

        skip_remaining = False
        for i, action in enumerate(actions, 1):
            if skip_remaining:
                action.status = "skipped"
                action.decided_at = datetime.now(timezone.utc).isoformat()
                store.update(action)
                self._audit.write(action, "skipped", detail="User chose skip-all")
                continue

            decision = self._prompt_action(action, i, len(actions))

            action.decided_at = datetime.now(timezone.utc).isoformat()

            if decision == "y":
                action.status = "approved"
                store.update(action)
                self._audit.write(action, "approved")
                console.print(f"  [green]✓ Approved[/green]\n")

            elif decision == "n":
                action.status = "rejected"
                store.update(action)
                self._audit.write(action, "rejected")
                console.print(f"  [red]✗ Rejected[/red]\n")

            elif decision == "s":
                action.status = "skipped"
                store.update(action)
                self._audit.write(action, "skipped", detail="User chose skip-all")
                console.print(f"  [dim]Skipping all remaining actions.[/dim]\n")
                skip_remaining = True

            elif decision == "q":
                action.status = "skipped"
                store.update(action)
                self._audit.write(action, "skipped", detail="User quit")
                console.print(f"  [dim]Exiting approval gate.[/dim]\n")
                skip_remaining = True

        return actions

    # ── Display helpers ───────────────────────────────────────────────────────

    def _print_summary_table(self, actions: list[Action]) -> None:
        table = Table(
            title=f"Proposed Actions ({len(actions)} total)",
            show_lines=True,
        )
        table.add_column("#", justify="right", style="dim", width=3)
        table.add_column("Category", style="cyan", width=12)
        table.add_column("Title", width=40)
        table.add_column("Resource", width=25)
        table.add_column("Reversibility", width=20)
        table.add_column("Blast", width=8)

        for i, a in enumerate(actions, 1):
            table.add_row(
                str(i),
                a.category,
                a.title,
                a.resource,
                _REVERSIBILITY_ICON[a.reversibility],
                f"[{'green' if a.blast_radius == 'low' else 'yellow' if a.blast_radius == 'medium' else 'red'}]{a.blast_radius}[/]",
            )
        console.print("\n", table, "\n")

    def _prompt_action(self, action: Action, index: int, total: int) -> str:
        color = _CATEGORY_COLOR.get(action.category, "white")
        rev_icon = _REVERSIBILITY_ICON[action.reversibility]

        # Block irreversible actions unless flag is set
        if action.reversibility == "irreversible" and not CONFIRM_DESTRUCTIVE:
            console.print(Panel(
                f"[bold]{action.title}[/bold]\n\n"
                f"[red]⚠  IRREVERSIBLE ACTION — auto-rejected.[/red]\n"
                f"Run with [cyan]--confirm-destructive[/cyan] to be prompted for irreversible actions.\n\n"
                f"Resource: [cyan]{action.resource}[/cyan]\n"
                f"Action:   {action.action_type}\n"
                f"Rollback: N/A",
                title=f"[{color}][{index}/{total}] {action.category.upper()}[/{color}]",
                border_style=color,
            ))
            return "n"

        console.print(Panel(
            f"[bold]{action.title}[/bold]\n\n"
            f"{action.description}\n\n"
            f"Resource:     [cyan]{action.resource}[/cyan]\n"
            f"Action type:  {action.action_type}\n"
            f"Reversibility: {rev_icon}\n"
            f"Blast radius: [{'green' if action.blast_radius == 'low' else 'yellow' if action.blast_radius == 'medium' else 'red'}]{action.blast_radius}[/]\n\n"
            f"[dim]Rollback:[/dim] {action.rollback_instructions}",
            title=f"[{color}][{index}/{total}] {action.category.upper()}[/{color}]",
            border_style=color,
        ))

        while True:
            choice = Prompt.ask(
                "  Decision",
                choices=["y", "n", "s", "q"],
                default="n",
                show_choices=True,
                show_default=True,
            ).lower()
            if choice in ("y", "n", "s", "q"):
                return choice
