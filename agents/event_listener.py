"""
agents/event_listener.py — Phase 3 event-driven trigger via HTTP webhook.

Starts a lightweight HTTP server that accepts GCP Cloud Monitoring alert
notifications delivered via a Pub/Sub push subscription.

When an alert fires:
  1. The GCP Monitoring → Pub/Sub → Push endpoint delivers a JSON payload.
  2. This server parses it, extracts the alert policy name and resource.
  3. It triggers an immediate focused run of the relevant agent domain.
  4. The Supervisor processes findings → policy engine → auto-approve/execute.

Setup (one-time GCP config):
  gcloud pubsub topics create cloud-ops-alerts
  gcloud alpha monitoring channels create --type=pubsub \
      --channel-labels=topic=projects/<PROJECT>/topics/cloud-ops-alerts \
      --display-name="Cloud Ops Agent"
  gcloud pubsub subscriptions create cloud-ops-push \
      --topic=cloud-ops-alerts \
      --push-endpoint=http://<YOUR_SERVER>:<PORT>/webhook \
      --ack-deadline=60

Run:
  python main.py --listen            # starts the webhook server
  PHASE=3 python main.py --listen    # starts server in Phase 3 autonomous mode

The server runs on EVENT_LISTENER_PORT (default 8080).
"""
from __future__ import annotations

import base64
import json
import logging
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from config import EVENT_LISTENER_PORT, PHASE, ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

# ── Alert → Agent domain mapping ─────────────────────────────────────────────
# Maps keywords found in alert policy names → agent domain to run.
# If no keyword matches, the full supervisor cycle is run.

_ALERT_DOMAIN_MAP: dict[str, str] = {
    "firewall":    "security",
    "bucket":      "security",
    "iam":         "security",
    "billing":     "cost",
    "budget":      "cost",
    "spend":       "cost",
    "cpu":         "infra",
    "memory":      "infra",
    "disk":        "infra",
    "instance":    "infra",
    "latency":     "incident",
    "uptime":      "incident",
    "error_rate":  "incident",
    "error rate":  "incident",
    "build":       "deployment",
    "deploy":      "deployment",
    "run":         "deployment",
}


def _parse_pubsub_payload(body: bytes) -> dict[str, Any] | None:
    """
    Parse a Pub/Sub push notification body.
    Returns the decoded monitoring incident dict, or None if unparseable.

    Pub/Sub push format:
    {
      "message": {
        "data": "<base64-encoded JSON>",
        "attributes": {...},
        "messageId": "...",
        "publishTime": "..."
      },
      "subscription": "projects/.../subscriptions/..."
    }
    """
    try:
        envelope = json.loads(body.decode("utf-8"))
        raw_data = envelope.get("message", {}).get("data", "")
        decoded = base64.b64decode(raw_data).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _determine_domain(incident: dict[str, Any]) -> str | None:
    """
    Examine the incident payload and return the most relevant agent domain,
    or None to trigger a full supervisor cycle.
    """
    policy_name = (
        incident.get("incident", {}).get("policy_name", "") or
        incident.get("condition_name", "") or
        incident.get("summary", "")
    ).lower()

    for keyword, domain in _ALERT_DOMAIN_MAP.items():
        if keyword in policy_name:
            return domain
    return None  # full cycle


def _trigger_run(domain: str | None, incident: dict[str, Any]) -> None:
    """
    Run the agent cycle in a background thread so the HTTP handler can
    return 200 immediately (Pub/Sub requires ACK within ack-deadline).
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — cannot run agent cycle.")
        return

    trigger_label = f"alert:{incident.get('incident', {}).get('policy_name', 'unknown')}"

    def _run():
        try:
            from agents.supervisor import SupervisorAgent
            supervisor = SupervisorAgent()
            if domain:
                # Scoped run — only the relevant domain
                logger.info(f"[event_listener] Triggering scoped run for domain='{domain}', trigger='{trigger_label}'")
                supervisor.run_scoped(domain=domain, trigger=trigger_label)
            else:
                # Full cycle
                logger.info(f"[event_listener] Triggering full cycle, trigger='{trigger_label}'")
                supervisor.run(trigger=trigger_label)
        except Exception as e:
            logger.exception(f"[event_listener] Agent cycle failed: {e}")

    thread = threading.Thread(target=_run, daemon=True, name="agent-cycle")
    thread.start()


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class WebhookHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for Pub/Sub push endpoint."""

    def do_POST(self):  # noqa: N802
        if self.path != "/webhook":
            self._reply(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        incident = _parse_pubsub_payload(body)
        if incident is None:
            logger.warning("[event_listener] Received unparseable payload — ACKing anyway.")
            self._reply(200, "ok")
            return

        domain = _determine_domain(incident)
        logger.info(
            f"[event_listener] Alert received. Domain='{domain or 'full'}'. "
            f"Phase={PHASE}. Triggering run."
        )

        # Always ACK quickly; run the agent in the background
        _trigger_run(domain, incident)
        self._reply(200, "ok")

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._reply(200, json.dumps({
                "status": "ok",
                "phase": PHASE,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        else:
            self._reply(404, "Not found")

    def _reply(self, code: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):  # suppress default access log spam
        logger.debug(fmt % args)


# ── Server ────────────────────────────────────────────────────────────────────

class EventListener:
    """
    Starts the webhook HTTP server.

    Usage:
        listener = EventListener()
        listener.start()          # blocking
        listener.start_async()    # non-blocking (background thread)
    """

    def __init__(self, port: int | None = None):
        self._port = port or EVENT_LISTENER_PORT

    def start(self) -> None:
        """Start the server (blocking — runs until KeyboardInterrupt)."""
        server = HTTPServer(("0.0.0.0", self._port), WebhookHandler)
        logger.info(f"[event_listener] Webhook server listening on port {self._port}")
        print(f"  Webhook: http://0.0.0.0:{self._port}/webhook")
        print(f"  Health:  http://0.0.0.0:{self._port}/health")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.shutdown()

    def start_async(self) -> threading.Thread:
        """Start the server in a daemon thread. Returns the thread."""
        t = threading.Thread(target=self.start, daemon=True, name="webhook-server")
        t.start()
        return t
