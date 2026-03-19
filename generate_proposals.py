"""
generate_proposals.py — Generate action proposals from the latest findings
without running a fresh GCP scan.

Reads the most recent reports/findings_*.json, calls Claude via ProposalEngine,
and saves the proposed actions to reports/actions_web_<run_id>.json.

Usage:
    python generate_proposals.py

Output (last line of stdout):
    {"success": true, "count": N, "file": "reports/actions_web_<run_id>.json"}
  or
    {"error": "..."}
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# ── Must be set BEFORE any project imports ────────────────────────────────────
os.environ["PHASE"] = "2"

from dotenv import load_dotenv  # noqa: E402 (intentional late import position)

BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))

# ── Project imports (after env is configured) ─────────────────────────────────
from memory.store import Finding, FindingsStore        # noqa: E402
from memory.actions import Action, ActionsStore        # noqa: E402
from agents.proposal_engine import ProposalEngine      # noqa: E402


def find_latest_findings(reports_dir: Path) -> Path | None:
    files = sorted(
        reports_dir.glob("findings_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def main() -> None:
    reports_dir = BASE_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    findings_path = find_latest_findings(reports_dir)
    if findings_path is None:
        print(json.dumps({"error": "No findings_*.json in reports/. Run a Phase 1 scan first."}))
        sys.exit(1)

    try:
        raw = json.loads(findings_path.read_text())
    except Exception as e:
        print(json.dumps({"error": f"Could not read {findings_path.name}: {e}"}))
        sys.exit(1)

    run_id: str = raw.get("run_id", findings_path.stem.replace("findings_", ""))
    raw_findings: list[dict] = raw.get("findings", [])

    if not raw_findings:
        print(json.dumps({"error": "Findings file is empty. Run a Phase 1 scan first."}))
        sys.exit(1)

    # Populate findings store
    findings_store = FindingsStore(persist_dir=str(reports_dir))
    findings: list[Finding] = []
    for item in raw_findings:
        try:
            findings.append(Finding(**item))
        except Exception:
            continue
    findings_store.add_many(findings)

    critical_high = findings_store.critical_and_high()
    if not critical_high:
        print(json.dumps({
            "error": (
                f"No CRITICAL or HIGH findings in {findings_path.name}. "
                "Proposals are only generated for critical/high severity."
            )
        }))
        sys.exit(0)

    # Generate proposals via Claude
    try:
        engine = ProposalEngine()
        actions: list[Action] = engine.propose(critical_high, run_id=run_id)
    except Exception as e:
        print(json.dumps({"error": f"ProposalEngine failed: {e}\n{traceback.format_exc()}"}))
        sys.exit(1)

    if not actions:
        print(json.dumps({"error": "ProposalEngine returned no actions (nothing actionable)."}))
        sys.exit(0)

    # Persist
    actions_store = ActionsStore(persist_dir=str(reports_dir))
    actions_store.add_many(actions)

    web_run_id = f"web_{run_id}"
    try:
        out_path = actions_store.flush_to_disk(run_id=web_run_id)
    except Exception as e:
        print(json.dumps({"error": f"Could not save actions file: {e}"}))
        sys.exit(1)

    print(json.dumps({
        "success": True,
        "count": len(actions),
        "file": str(out_path),
        "run_id": web_run_id,
    }))


if __name__ == "__main__":
    main()
