"""
web_runner.py — Execution helper for the Streamlit web UI.

Loads a saved actions JSON file, marks the user-approved action IDs as
"approved", then runs ExecutionEngine. Bypasses the CLI approval gate —
approval decisions come from the Streamlit UI.

Usage:
    python web_runner.py \
        --actions-file reports/actions_web_<run_id>.json \
        --approved-ids id1,id2,id3 \
        [--dry-run]

Output (last line of stdout):
    [{"id": "...", "title": "...", "status": "succeeded", "result": "..."}, ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse CLI args FIRST — before any env mutation or project imports."""
    parser = argparse.ArgumentParser(description="Web execution helper for Cloud Ops AI Agent")
    parser.add_argument(
        "--actions-file", required=True,
        help="Path to the actions_*.json file",
    )
    parser.add_argument(
        "--approved-ids", default="",
        help="Comma-separated action IDs approved by the user",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Simulate execution — no GCP changes",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # ── Set env vars BEFORE any project imports ───────────────────────────────
    os.environ["PHASE"] = "2"
    os.environ["DRY_RUN"] = "true" if args.dry_run else "false"

    from dotenv import load_dotenv  # noqa: E402

    BASE_DIR = Path(__file__).parent
    load_dotenv(dotenv_path=BASE_DIR / ".env")
    sys.path.insert(0, str(BASE_DIR))

    # ── Project imports (after env is set) ────────────────────────────────────
    from memory.actions import Action, ActionsStore  # noqa: E402
    from audit.log import AuditLogger                # noqa: E402
    from execution.engine import ExecutionEngine     # noqa: E402

    # ── Load actions file ─────────────────────────────────────────────────────
    actions_path = Path(args.actions_file)
    if not actions_path.exists():
        print(json.dumps([{"error": f"Actions file not found: {actions_path}"}]))
        sys.exit(1)

    try:
        raw = json.loads(actions_path.read_text())
    except Exception as e:
        print(json.dumps([{"error": f"Could not read actions file: {e}"}]))
        sys.exit(1)

    raw_actions: list[dict] = raw.get("actions", []) if isinstance(raw, dict) else raw
    if not raw_actions:
        print(json.dumps([{"error": "No actions found in file."}]))
        sys.exit(0)

    # ── Parse approved IDs ────────────────────────────────────────────────────
    approved_ids: set[str] = set()
    if args.approved_ids.strip():
        approved_ids = {a.strip() for a in args.approved_ids.split(",") if a.strip()}

    # ── Build Action objects, mark approved ones ──────────────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    all_actions: list[Action] = []

    for item in raw_actions:
        try:
            action = Action(**item)
        except Exception as e:
            print(f"Skipping malformed action {item.get('id', '?')}: {e}", file=sys.stderr)
            continue

        if action.id in approved_ids:
            action.status = "approved"
            action.decided_by = "human_web"
            action.decided_at = now_iso

        all_actions.append(action)

    # ── Set up stores and logger ──────────────────────────────────────────────
    reports_dir = BASE_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    actions_store = ActionsStore(persist_dir=str(reports_dir))
    actions_store.add_many(all_actions)

    audit_dir = BASE_DIR / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    web_run_id = f"web_exec_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    audit_logger = AuditLogger(run_id=web_run_id, log_dir=str(audit_dir))

    # ── Execute ───────────────────────────────────────────────────────────────
    engine = ExecutionEngine(audit_logger=audit_logger, dry_run=args.dry_run)

    try:
        executed = engine.execute(all_actions, actions_store)
    except Exception as e:
        print(json.dumps([{
            "error": f"ExecutionEngine raised: {e}",
            "traceback": traceback.format_exc(),
        }]))
        sys.exit(1)

    # Flush updated state
    try:
        actions_store.flush_to_disk(run_id=web_run_id)
    except Exception as e:
        print(f"Warning: could not flush actions to disk: {e}", file=sys.stderr)

    # ── Build result list ─────────────────────────────────────────────────────
    executed_map = {a.id: a for a in executed}
    results = []

    for action in all_actions:
        if action.id in executed_map:
            ea = executed_map[action.id]
            results.append({
                "id":     ea.id,
                "title":  ea.title,
                "status": ea.status,
                "result": ea.outcome or "",
            })
        elif action.id in approved_ids:
            results.append({
                "id":     action.id,
                "title":  action.title,
                "status": "failed",
                "result": "Approved but not returned by execution engine.",
            })
        else:
            results.append({
                "id":     action.id,
                "title":  action.title,
                "status": "rejected",
                "result": "Not approved by user.",
            })

    # Emit JSON result — parsed by streamlit_app.py
    print(json.dumps(results))


if __name__ == "__main__":
    main()
