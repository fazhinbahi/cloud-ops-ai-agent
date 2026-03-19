"""
integrations/slack_bot.py — Phase 4 two-way Slack ChatOps interface.

Uses Slack Bolt with Socket Mode so no public URL is needed.
The bot listens for @mentions and slash commands, interprets them
with Claude, and dispatches to the appropriate system function.

Supported commands (natural language via @mention or slash):
  @cloudops status            → run full observe cycle, post summary
  @cloudops run <domain>      → run a single agent domain
  @cloudops approve <id>      → approve a pending action by ID
  @cloudops reject <id>       → reject a pending action by ID
  @cloudops history           → show cross-run pattern summary
  @cloudops policy            → show current auto-approval policy
  @cloudops compliance        → run compliance checks and post score
  /cloudops <any of the above>

Setup:
  1. Create a Slack App at https://api.slack.com/apps
  2. Enable Socket Mode (Settings → Socket Mode)
  3. Add Bot Token Scopes: app_mentions:read, chat:write, commands
  4. Copy SLACK_BOT_TOKEN (xoxb-...) and SLACK_APP_TOKEN (xapp-...)
     into .env

Run:
  PHASE=4 python main.py --slack
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from config import (
    SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_OPS_CHANNEL,
    ANTHROPIC_API_KEY, PHASE,
)

logger = logging.getLogger(__name__)

# ── Intent parser ─────────────────────────────────────────────────────────────

_INTENT_SYSTEM = """You are the command parser for a GCP cloud operations Slack bot.
Parse the user's message and return a JSON object with:
{
  "intent": "status|run_agent|approve|reject|history|policy|compliance|help|unknown",
  "domain": "<agent domain if intent is run_agent, else null>",
  "action_id": "<action id string if intent is approve/reject, else null>"
}

Valid domains: infra, cost, security, incident, deployment, data
Return ONLY the JSON. No explanation.
"""


def _parse_intent(text: str) -> dict[str, Any]:
    """Ask Claude to parse a natural-language command into a structured intent."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # fast + cheap for intent parsing
            max_tokens=128,
            system=_INTENT_SYSTEM,
            messages=[{"role": "user", "content": text}],
        )
        raw = next((b.text for b in response.content if b.type == "text"), "{}")
        return json.loads(raw)
    except Exception:
        return {"intent": "unknown", "domain": None, "action_id": None}


# ── Command handlers ──────────────────────────────────────────────────────────

def _handle_status(say) -> None:
    say("Running full observe cycle... this may take a minute.")
    try:
        from agents.supervisor import SupervisorAgent
        supervisor = SupervisorAgent()
        result = supervisor.run(trigger="slack")
        summary = result.get("summary", {})
        total = summary.get("total", 0)
        by_sev = summary.get("by_severity", {})
        sev_str = " | ".join(f"{k}: {v}" for k, v in by_sev.items()) or "none"
        say(
            f":white_check_mark: *Observe cycle complete.*\n"
            f"Total findings: *{total}*\n"
            f"By severity: {sev_str}\n"
            f"Run ID: `{result.get('run_id', 'n/a')}`"
        )
    except Exception as e:
        say(f":x: Error running observe cycle: `{e}`")


def _handle_run_agent(domain: str, say) -> None:
    if not domain:
        say(":x: Please specify a domain: `infra`, `cost`, `security`, `incident`, `deployment`, `data`")
        return
    say(f"Running *{domain}* agent...")
    try:
        from agents.supervisor import SupervisorAgent
        supervisor = SupervisorAgent()
        result = supervisor.run_scoped(domain=domain, trigger="slack")
        say(
            f":white_check_mark: *{domain.capitalize()} agent complete.*\n"
            f"Findings: *{result.get('total_findings', 0)}*"
        )
    except Exception as e:
        say(f":x: Error running {domain} agent: `{e}`")


def _handle_approve(action_id: str, say, user: str) -> None:
    if not action_id:
        say(":x: Please provide an action ID: `approve <action_id>`")
        return
    try:
        from memory.actions import actions_store
        from datetime import datetime, timezone
        action = next((a for a in actions_store.all() if a.id.startswith(action_id)), None)
        if not action:
            say(f":x: No pending action found with ID starting with `{action_id}`.")
            return
        action.status = "approved"
        action.decided_by = f"slack:{user}"
        action.decided_at = datetime.now(timezone.utc).isoformat()
        actions_store.update(action)
        say(f":white_check_mark: Action *{action.title}* approved by <@{user}>.")
    except Exception as e:
        say(f":x: Error approving action: `{e}`")


def _handle_reject(action_id: str, say, user: str) -> None:
    if not action_id:
        say(":x: Please provide an action ID: `reject <action_id>`")
        return
    try:
        from memory.actions import actions_store
        from datetime import datetime, timezone
        action = next((a for a in actions_store.all() if a.id.startswith(action_id)), None)
        if not action:
            say(f":x: No pending action found with ID starting with `{action_id}`.")
            return
        action.status = "rejected"
        action.decided_by = f"slack:{user}"
        action.decided_at = datetime.now(timezone.utc).isoformat()
        actions_store.update(action)
        say(f":no_entry: Action *{action.title}* rejected by <@{user}>.")
    except Exception as e:
        say(f":x: Error rejecting action: `{e}`")


def _handle_history(say) -> None:
    try:
        from memory.history import history_db
        summary = history_db.summary()
        patterns = summary.get("top_patterns", [])
        pat_str = "\n".join(
            f"  • `{p['resource']}` — {p['check_type']} ({p['occurrences']}x)"
            for p in patterns[:5]
        ) or "  _No recurring patterns found._"
        say(
            f":bar_chart: *Cross-Run History ({summary['window_days']}d window)*\n"
            f"Findings: *{summary['total_findings']}* | Actions: *{summary['total_actions']}* | "
            f"Patterns: *{summary['recurring_patterns']}*\n\n"
            f"*Top patterns:*\n{pat_str}"
        )
    except Exception as e:
        say(f":x: Error fetching history: `{e}`")


def _handle_policy(say) -> None:
    try:
        from agents.policy_engine import PolicyEngine
        policy = PolicyEngine()
        s = policy.summary()
        say(
            f":shield: *Phase 3 Policy*\n"
            f"File: `{s['policy_file']}`\n"
            f"Rules: *{s['rules_loaded']}* | Default: *{s['default_decision']}*"
        )
    except Exception as e:
        say(f":x: Error fetching policy: `{e}`")


def _handle_compliance(say) -> None:
    say(":mag: Running compliance checks...")
    try:
        from agents.compliance_agent import ComplianceAgent
        agent = ComplianceAgent()
        findings = agent.run()
        failed = len(findings)
        say(
            f":white_check_mark: *Compliance scan complete.*\n"
            f"Failed controls: *{failed}*\n"
            f"{'_All controls passed._' if failed == 0 else 'See terminal for full report.'}"
        )
    except Exception as e:
        say(f":x: Error running compliance: `{e}`")


def _handle_help(say) -> None:
    say(
        "*Cloud Ops Bot — Available Commands*\n\n"
        "• `@cloudops status` — run full observe cycle\n"
        "• `@cloudops run <domain>` — run a single agent (infra/cost/security/incident/deployment/data)\n"
        "• `@cloudops approve <id>` — approve a pending action\n"
        "• `@cloudops reject <id>` — reject a pending action\n"
        "• `@cloudops history` — show cross-run pattern summary\n"
        "• `@cloudops policy` — show auto-approval policy\n"
        "• `@cloudops compliance` — run CIS GCP compliance checks\n"
    )


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def _dispatch(text: str, say, user: str = "unknown") -> None:
    """Parse and dispatch a user message in a background thread."""
    def _run():
        parsed = _parse_intent(text)
        intent = parsed.get("intent", "unknown")

        if intent == "status":
            _handle_status(say)
        elif intent == "run_agent":
            _handle_run_agent(parsed.get("domain", ""), say)
        elif intent == "approve":
            _handle_approve(parsed.get("action_id", ""), say, user)
        elif intent == "reject":
            _handle_reject(parsed.get("action_id", ""), say, user)
        elif intent == "history":
            _handle_history(say)
        elif intent == "policy":
            _handle_policy(say)
        elif intent == "compliance":
            _handle_compliance(say)
        else:
            _handle_help(say)

    threading.Thread(target=_run, daemon=True).start()


# ── Slack Bolt app ─────────────────────────────────────────────────────────────

class CloudOpsSlackBot:
    """
    Two-way Slack bot using Bolt + Socket Mode.
    Requires SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env.
    """

    def __init__(self):
        self._app = None
        self._handler = None
        self._configured = bool(SLACK_BOT_TOKEN and SLACK_APP_TOKEN)

    def is_configured(self) -> bool:
        return self._configured

    def post(self, message: str, channel: str | None = None) -> None:
        """Post a plain message to the ops channel (one-way notification)."""
        if not self._configured:
            logger.debug(f"[slack] Would post: {message[:100]}")
            return
        try:
            if self._app:
                self._app.client.chat_postMessage(
                    channel=channel or SLACK_OPS_CHANNEL,
                    text=message,
                )
            else:
                import requests
                from config import SLACK_WEBHOOK_URL
                if SLACK_WEBHOOK_URL:
                    requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=5)
        except Exception as e:
            logger.warning(f"[slack] post failed: {e}")

    def start(self) -> None:
        """Start the Socket Mode bot (blocking)."""
        if not self._configured:
            logger.error("[slack] SLACK_BOT_TOKEN or SLACK_APP_TOKEN not set. Bot not started.")
            print("  Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN in .env to enable the Slack bot.")
            return

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            logger.error("[slack] slack-bolt not installed. Run: pip install slack-bolt")
            print("  Run: .venv/bin/pip install slack-bolt")
            return

        app = App(token=SLACK_BOT_TOKEN)
        self._app = app

        @app.event("app_mention")
        def handle_mention(event, say):
            text = event.get("text", "")
            user = event.get("user", "unknown")
            # Strip the bot mention prefix (<@BOTID> ...)
            if ">" in text:
                text = text.split(">", 1)[-1].strip()
            _dispatch(text, say, user)

        @app.command("/cloudops")
        def handle_slash(ack, command, say):
            ack()
            text = command.get("text", "")
            user = command.get("user_id", "unknown")
            _dispatch(text, say, user)

        handler = SocketModeHandler(app, SLACK_APP_TOKEN)
        logger.info("[slack] Starting Socket Mode bot...")
        print(f"  Slack bot connected. Listening in {SLACK_OPS_CHANNEL}.")
        handler.start()

    def start_async(self) -> threading.Thread:
        """Start the bot in a daemon thread."""
        t = threading.Thread(target=self.start, daemon=True, name="slack-bot")
        t.start()
        return t


# ── Module-level singleton ─────────────────────────────────────────────────────
slack_bot = CloudOpsSlackBot()
