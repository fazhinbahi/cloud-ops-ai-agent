"""
streamlit_app.py — Streamlit web UI for the Cloud Ops Multi-Agent System.

Pages:
  Overview          — summary metrics, scan history, phase explanations
  Phase 1 — Scan    — trigger a scan, filter and browse findings
  Phase 2 — Actions — review proposals, approve/reject, dry-run or live execute
  Phase 3 — Autonomous — view policy rules, trigger autonomous dry-run

Usage:
    streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st
import yaml
from dotenv import dotenv_values

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
REPORTS_DIR = BASE_DIR / "reports"
POLICIES_FILE = BASE_DIR / "policies" / "default.yaml"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Cloud Ops AI Agent",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Display helpers ───────────────────────────────────────────────────────────
SEV_ICON = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🔵",
    "info":     "⚪",
}

AGENT_ICON = {
    "security":   "🔒",
    "infra":      "🏗️",
    "cost":       "💰",
    "incident":   "🚨",
    "deployment": "🚀",
    "data":       "📊",
    "supervisor": "🧠",
}

BLAST_ICON = {"low": "🟢", "medium": "🟡", "high": "🔴"}
REV_ICON   = {"reversible": "↩️", "semi-reversible": "⚠️", "irreversible": "🚫"}
SEV_ORDER  = ["critical", "high", "medium", "low", "info"]


# ── Data helpers ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_env() -> dict:
    env_path = BASE_DIR / ".env"
    return dict(dotenv_values(str(env_path))) if env_path.exists() else {}


def get_active_project() -> str:
    return st.session_state.get("active_project") or load_env().get("GOOGLE_CLOUD_PROJECT", "")


def get_active_credentials() -> str:
    return st.session_state.get("active_credentials") or load_env().get("GOOGLE_APPLICATION_CREDENTIALS", "")


def list_credential_files() -> list[Path]:
    cred_dir = BASE_DIR / "credentials"
    return sorted(cred_dir.glob("*.json")) if cred_dir.exists() else []


def list_findings_files() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("findings_*.json"), reverse=True)


def list_actions_files() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    return sorted(REPORTS_DIR.glob("actions_*.json"), reverse=True)


def load_json(path: Path) -> dict | list:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def latest_findings() -> dict:
    files = list_findings_files()
    return load_json(files[0]) if files else {}


def run_subprocess(cmd: list[str], timeout: int = 600) -> tuple[bool, str]:
    """Run cmd in BASE_DIR; return (success, combined_output)."""
    env = os.environ.copy()
    project = get_active_project()
    creds = get_active_credentials()
    if project:
        env["GOOGLE_CLOUD_PROJECT"] = project
    if creds:
        creds_path = creds if Path(creds).is_absolute() else str(BASE_DIR / creds)
        env["GOOGLE_APPLICATION_CREDENTIALS"] = creds_path
    try:
        r = subprocess.run(
            cmd, cwd=str(BASE_DIR), capture_output=True,
            text=True, timeout=timeout, env=env,
        )
        out = r.stdout + ("\n" + r.stderr if r.stderr.strip() else "")
        return r.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, f"Timed out after {timeout}s."
    except Exception as e:
        return False, f"Subprocess error: {e}"


def default_approval(action: dict) -> bool:
    return (
        action.get("reversibility") != "irreversible"
        and action.get("blast_radius", "high") in ("low", "medium")
    )


# ── Sidebar ───────────────────────────────────────────────────────────────────
def render_sidebar() -> str:
    env = load_env()
    active_project = get_active_project()

    data = latest_findings()
    by_sev = data.get("summary", {}).get("by_severity", {})
    critical = by_sev.get("critical", 0)
    high = by_sev.get("high", 0)

    gen_at = data.get("generated_at", "")
    if gen_at:
        try:
            last_scan = datetime.fromisoformat(gen_at).strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            last_scan = gen_at[:16]
    else:
        last_scan = "No scans yet"

    with st.sidebar:
        st.title("☁️ Cloud Ops AI")
        st.divider()

        # ── Demo Mode ─────────────────────────────────────────────────────────
        demo_dir = BASE_DIR / "demo"
        if st.session_state.get("demo_mode"):
            st.success("🎯 DEMO MODE ACTIVE  \n`northstar-prod-001`")
            if st.button("✕ Exit Demo", key="exit_demo", use_container_width=True):
                st.session_state.pop("demo_mode", None)
                for k in ("active_project", "active_credentials", "active_credentials_name"):
                    st.session_state.pop(k, None)
                st.rerun()
        else:
            if st.button("🎯 Load Demo Data", key="load_demo", use_container_width=True):
                ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                REPORTS_DIR.mkdir(exist_ok=True)
                src_f = demo_dir / "findings_demo.json"
                src_a = demo_dir / "actions_demo.json"
                if src_f.exists():
                    dst_f = REPORTS_DIR / f"findings_{ts}.json"
                    dst_a = REPORTS_DIR / f"actions_{ts}.json"
                    dst_f.write_bytes(src_f.read_bytes())
                    if src_a.exists():
                        dst_a.write_bytes(src_a.read_bytes())
                    st.session_state["demo_mode"] = True
                    st.session_state["active_project"] = "northstar-prod-001"
                    st.session_state.pop("active_credentials", None)
                    st.rerun()
                else:
                    st.error("Demo data files not found in demo/ folder.")
        st.divider()

        # ── GCP Project Switcher ───────────────────────────────────────────────
        with st.expander("🔧 Switch GCP Project", expanded=False):
            default_project = env.get("GOOGLE_CLOUD_PROJECT", "")
            new_project = st.text_input(
                "Project ID",
                value=st.session_state.get("active_project", default_project),
                placeholder="e.g. my-gcp-project-123",
                key="project_input",
            )

            # ── Upload a new service account key ──────────────────────────────
            uploaded = st.file_uploader(
                "Upload Service Account Key (JSON)",
                type="json",
                key="sa_uploader",
                help="Upload a GCP service account key file. It will be saved to the credentials/ folder.",
            )
            if uploaded is not None:
                try:
                    raw_bytes = uploaded.read()
                    parsed = json.loads(raw_bytes)
                    # Basic validation — must look like a service account key
                    if parsed.get("type") != "service_account":
                        st.error("Not a valid service account key (missing `\"type\": \"service_account\"`).")
                    else:
                        dest = BASE_DIR / "credentials" / uploaded.name
                        dest.write_bytes(raw_bytes)
                        st.success(f"Saved → `credentials/{uploaded.name}`")
                        st.session_state["pending_cred_name"] = uploaded.name
                        st.rerun()
                except Exception as e:
                    st.error(f"Could not save file: {e}")

            # ── Select from saved credentials ─────────────────────────────────
            cred_files = list_credential_files()
            cred_options = ["(default from .env)"] + [f.name for f in cred_files]
            # Auto-select a freshly uploaded file if present
            pending = st.session_state.pop("pending_cred_name", None)
            if pending and pending in cred_options:
                st.session_state["active_credentials_name"] = pending
            current_cred_name = st.session_state.get("active_credentials_name", cred_options[0])
            sel_idx = cred_options.index(current_cred_name) if current_cred_name in cred_options else 0
            selected_cred = st.selectbox("Service Account Key", cred_options, index=sel_idx)

            if st.button("Apply", key="apply_project", use_container_width=True, type="primary"):
                st.session_state["active_project"] = new_project.strip()
                st.session_state["active_credentials_name"] = selected_cred
                if selected_cred == "(default from .env)":
                    st.session_state["active_credentials"] = env.get("GOOGLE_APPLICATION_CREDENTIALS", "")
                else:
                    st.session_state["active_credentials"] = str(BASE_DIR / "credentials" / selected_cred)
                st.rerun()

            if st.button("Reset to default", key="reset_project", use_container_width=True):
                for k in ("active_project", "active_credentials", "active_credentials_name"):
                    st.session_state.pop(k, None)
                st.rerun()

        st.markdown(f"**Project**  \n`{active_project or '—'}`")
        st.markdown(f"**Last scan**  \n{last_scan}")
        if critical > 0 or high > 0:
            st.error(f"🔴 {critical} Critical   🟠 {high} High")
        elif data:
            st.success("No critical/high findings")
        st.divider()
        page = st.radio(
            "Navigate",
            [
                "🏠 Overview",
                "🔍 Phase 1 — Scan",
                "⚡ Phase 2 — Actions",
                "🤖 Phase 3 — Autonomous",
                "💸 Phase 4 — FinOps  *(coming soon)*",
                "🧠 Phase 5 — RCA  *(coming soon)*",
            ],
            label_visibility="collapsed",
        )
        st.divider()
        st.caption("Cloud Ops Multi-Agent System")

    return page


# ── Page: Overview ────────────────────────────────────────────────────────────
def page_overview() -> None:
    st.header("🏠 Overview")

    data = latest_findings()
    if data:
        summary = data.get("summary", {})
        by_sev = summary.get("by_severity", {})
        by_agent = summary.get("by_agent", {})
        run_id = data.get("run_id", "—")
        gen_at = data.get("generated_at", "")
        if gen_at:
            try:
                gen_at = datetime.fromisoformat(gen_at).strftime("%Y-%m-%d %H:%M:%S UTC")
            except Exception:
                pass

        st.subheader("Latest Scan")
        st.caption(f"Run `{run_id}` · {gen_at}")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🔴 Critical", by_sev.get("critical", 0))
        c2.metric("🟠 High",     by_sev.get("high", 0))
        c3.metric("🟡 Medium",   by_sev.get("medium", 0))
        c4.metric("🔵 Low",      by_sev.get("low", 0))
        c5.metric("⚪ Info",     by_sev.get("info", 0))

        if by_agent:
            st.markdown("**Findings by agent**")
            a_cols = st.columns(len(by_agent))
            for i, (agent, count) in enumerate(by_agent.items()):
                a_cols[i].metric(f"{AGENT_ICON.get(agent, '🔧')} {agent.title()}", count)
    else:
        st.info("No findings yet. Go to **Phase 1 — Scan** to run your first scan.")

    st.divider()
    st.subheader("Scan History")
    findings_files = list_findings_files()
    if findings_files:
        rows = []
        for f in findings_files:
            d = load_json(f)
            if not isinstance(d, dict):
                continue
            s = d.get("summary", {})
            bsev = s.get("by_severity", {})
            rows.append({
                "Run ID":    d.get("run_id", f.stem),
                "Generated": d.get("generated_at", "")[:19].replace("T", " "),
                "Total":     s.get("total", 0),
                "Critical":  bsev.get("critical", 0),
                "High":      bsev.get("high", 0),
                "Medium":    bsev.get("medium", 0),
                "Low":       bsev.get("low", 0),
            })
        st.dataframe(rows, use_container_width=True)
    else:
        st.caption("No scan history.")

    st.divider()
    st.subheader("How It Works")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
**🔍 Phase 1 — Observe**

Six specialist AI agents scan your GCP project in parallel:
Infrastructure, Security, Cost, Incident, Deployment, and Data.

Findings are classified by severity and saved to `reports/`. No changes
are ever made to your infrastructure.
        """)
    with col2:
        st.markdown("""
**⚡ Phase 2 — Supervised Action**

Claude analyses Critical/High findings and proposes targeted, reversible fixes.

Each action shows blast radius, reversibility, description, and step-by-step
rollback instructions. You approve or reject each one before anything runs.
        """)
    with col3:
        st.markdown("""
**🤖 Phase 3 — Autonomous**

Policy rules define which actions are safe to auto-approve (e.g., firewall
restriction) and which always need a human (e.g., VM deletion).

Dry-run mode lets you verify what would happen before going live.
        """)

    st.divider()
    st.subheader("Coming Soon")
    col4, col5 = st.columns(2)
    with col4:
        st.info("""
**💸 Phase 4 — FinOps Agent** *(Coming Soon)*

A dedicated cost intelligence layer that goes beyond flagging idle resources.

**What it will do:**
- **Committed Use Discount analysis** — identifies workloads eligible for 1-year or 3-year CUDs and calculates exact projected savings before recommending any commitment
- **Right-sizing with confidence scores** — cross-references 30 days of CPU, memory, and network utilisation to recommend the optimal machine type, with a confidence % attached to every recommendation
- **Cost anomaly detection** — establishes a rolling 14-day baseline per service and region, and flags deviations before they appear on your billing invoice
- **Budget alert gap detection** — scans every project and service for missing or misconfigured budget alerts, and configures them automatically
- **Cross-project spend consolidation** — maps total spend across all projects in an org and surfaces which team, service, or environment is driving growth

*Early access pilots launching soon — contact us to join the waitlist.*
        """)
    with col5:
        st.info("""
**🧠 Phase 5 — Root Cause Analysis Agent** *(Coming Soon)*

Autonomous incident investigation that starts working the moment something breaks — before an engineer even joins the call.

**What it will do:**
- **Automated log correlation** — pulls error logs across all affected services for the preceding 6 hours and identifies the first error timestamp, tracing it forward through dependent services
- **Deployment correlation** — checks whether a release, config change, or infrastructure event occurred in the preceding 4 hours and links it to the incident timeline
- **Infrastructure change detection** — identifies autoscaler events, node replacements, quota limit hits, and network changes that coincide with the incident window
- **External signal correlation** — cross-references GCP service health dashboards, Cloud Monitoring alerts, and uptime checks to rule out platform-level causes
- **Structured RCA report generation** — produces a timestamped incident report: Timeline → Root Cause → Blast Radius → Recommended Fix, ready to share with stakeholders in under 90 seconds

*Reduces mean time to resolution and eliminates the first 45 minutes of manual log trawling from every incident.*

*Early access pilots launching soon — contact us to join the waitlist.*
        """)


# ── Page: Phase 1 ─────────────────────────────────────────────────────────────
def page_scan() -> None:
    st.header("🔍 Phase 1 — Scan")
    st.markdown("Run all six AI agents against your live GCP project and collect findings.")

    if st.button("▶ Run Scan", type="primary"):
        with st.spinner("Scanning GCP project — this may take 2–5 minutes…"):
            ok, output = run_subprocess([sys.executable, "main.py", "--trigger", "web"])
        if ok:
            st.success("Scan complete!")
        else:
            st.error("Scan finished with errors — check output below.")
        with st.expander("Subprocess output", expanded=not ok):
            st.code(output or "(no output)", language="text")
        st.rerun()

    st.divider()

    findings_files = list_findings_files()
    if not findings_files:
        st.info("No findings yet. Click **Run Scan** to start.")
        return

    file_labels = [f.name for f in findings_files]
    selected = st.selectbox("Findings file", file_labels, index=0)
    data = load_json(REPORTS_DIR / selected)
    if not isinstance(data, dict):
        st.error("Could not load file.")
        return

    summary = data.get("summary", {})
    by_sev = summary.get("by_severity", {})
    by_agent = summary.get("by_agent", {})

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔴 Critical", by_sev.get("critical", 0))
    c2.metric("🟠 High",     by_sev.get("high", 0))
    c3.metric("🟡 Medium",   by_sev.get("medium", 0))
    c4.metric("🔵 Low",      by_sev.get("low", 0))
    c5.metric("⚪ Info",     by_sev.get("info", 0))

    with st.expander("Breakdown by agent"):
        if by_agent:
            a_cols = st.columns(max(len(by_agent), 1))
            for i, (agent, count) in enumerate(by_agent.items()):
                a_cols[i].metric(f"{AGENT_ICON.get(agent, '🔧')} {agent.title()}", count)

    st.divider()

    findings = data.get("findings", [])
    if not findings:
        st.info("No findings in this file.")
        return

    fc1, fc2 = st.columns(2)
    sev_filter = fc1.multiselect(
        "Severity", SEV_ORDER, default=SEV_ORDER,
        format_func=lambda s: f"{SEV_ICON.get(s, '')} {s.title()}",
    )
    agent_options = sorted({f.get("agent", "") for f in findings if f.get("agent")})
    agent_filter = fc2.multiselect(
        "Agent", agent_options, default=agent_options,
        format_func=lambda a: f"{AGENT_ICON.get(a, '🔧')} {a.title()}",
    )

    sev_rank = {s: i for i, s in enumerate(SEV_ORDER)}
    filtered = sorted(
        [f for f in findings if f.get("severity") in sev_filter and f.get("agent") in agent_filter],
        key=lambda f: sev_rank.get(f.get("severity", "info"), 99),
    )

    st.caption(f"Showing {len(filtered)} of {len(findings)} findings")

    for finding in filtered:
        sev   = finding.get("severity", "info")
        agent = finding.get("agent", "")
        title = finding.get("title", "(no title)")
        icon  = SEV_ICON.get(sev, "⚪")
        a_icon = AGENT_ICON.get(agent, "🔧")
        label = f"{icon} **{sev.upper()}** · {a_icon} {agent.title()} · {title}"

        with st.expander(label):
            col_a, col_b = st.columns([2, 1])
            with col_a:
                st.markdown("**Detail**")
                st.write(finding.get("detail", ""))
            with col_b:
                st.markdown(f"**Resource:** `{finding.get('resource', '—')}`")
                st.markdown(f"**Region:** `{finding.get('region', '—')}`")
                ts = finding.get("timestamp", "")
                if ts:
                    st.markdown(f"**Detected:** {ts[:19].replace('T', ' ')} UTC")


# ── Page: Phase 2 ─────────────────────────────────────────────────────────────
def page_actions() -> None:
    st.header("⚡ Phase 2 — Actions")
    st.markdown(
        "Generate AI-proposed remediation actions from Critical/High findings, "
        "review each one, then execute as dry run or live."
    )

    # Step 1 — Generate proposals
    st.subheader("Step 1 — Generate Proposals")
    col_btn, col_note = st.columns([1, 3])
    if col_btn.button("🧠 Generate Proposals", type="primary"):
        with st.spinner("Claude is analysing findings and proposing actions (~30s)…"):
            ok, output = run_subprocess([sys.executable, "generate_proposals.py"], timeout=180)
        if ok:
            # Parse JSON result from last line
            result = {}
            for line in reversed(output.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result = json.loads(line)
                        break
                    except Exception:
                        pass
            if result.get("success"):
                st.success(f"Generated {result.get('count', 0)} proposals → `{Path(result.get('file', '')).name}`")
            elif result.get("error"):
                st.warning(f"Proposal engine: {result['error']}")
            else:
                st.success("Proposals generated.")
        else:
            st.error("Proposal generation failed.")
        with st.expander("Output", expanded=not ok):
            st.code(output or "(no output)", language="text")
        st.rerun()
    col_note.caption("Reads from the latest findings file — no fresh GCP scan needed.")

    st.divider()

    # Step 2 — Review proposals
    actions_files = list_actions_files()
    if not actions_files:
        st.info("No proposals yet. Click **Generate Proposals** above.")
        return

    file_labels = [f.name for f in actions_files]
    selected = st.selectbox("Actions file", file_labels, index=0)
    selected_path = REPORTS_DIR / selected

    raw = load_json(selected_path)
    actions = raw.get("actions", []) if isinstance(raw, dict) else raw
    if not actions:
        st.info("No actions in this file.")
        return

    # Init approval state per file
    state_key = f"approvals_{selected}"
    if state_key not in st.session_state:
        st.session_state[state_key] = {a["id"]: default_approval(a) for a in actions}
    approvals: dict[str, bool] = st.session_state[state_key]

    st.subheader("Step 2 — Review Actions")
    st.caption(f"{len(actions)} actions · `{selected_path.name}`")

    for action in actions:
        aid         = action.get("id", "")
        title       = action.get("title", "(no title)")
        blast       = action.get("blast_radius", "low")
        rev         = action.get("reversibility", "reversible")
        category    = action.get("category", "")
        description = action.get("description", "")
        rollback    = action.get("rollback_instructions", "")
        resource    = action.get("resource", "")
        action_type = action.get("action_type", "")
        status      = action.get("status", "proposed")

        # Already executed — show outcome only
        if status in ("succeeded", "failed"):
            outcome_icon = "✅" if status == "succeeded" else "❌"
            outcome = action.get("outcome", "")
            if action.get("dry_run"):
                outcome = "[DRY RUN] " + outcome
            with st.expander(f"{outcome_icon} **{status.upper()}** · {title}"):
                st.write(outcome or "—")
            continue

        is_approved = approvals.get(aid, False)
        toggle_icon = "✅" if is_approved else "❌"
        blast_badge = f"{BLAST_ICON.get(blast, '?')} {blast}"
        rev_badge   = f"{REV_ICON.get(rev, '?')} {rev}"

        with st.expander(f"{toggle_icon} {blast_badge} · {title}"):
            col_left, col_right = st.columns([3, 1])
            with col_left:
                st.markdown("**Description**")
                st.write(description)
                if rollback:
                    with st.expander("Rollback instructions"):
                        st.markdown(rollback)
            with col_right:
                st.markdown(f"**Blast:** {blast_badge}")
                st.markdown(f"**Reversibility:** {rev_badge}")
                st.markdown(f"**Category:** {category}")
                st.markdown(f"**Type:** `{action_type}`")
                if resource:
                    st.markdown(f"**Resource:** `{resource}`")

            new_val = st.toggle("Approve", value=is_approved, key=f"toggle_{aid}")
            if new_val != is_approved:
                approvals[aid] = new_val
                st.session_state[state_key] = approvals
                st.rerun()

    # Step 3 — Execute
    st.divider()
    st.subheader("Step 3 — Execute")

    approved_ids = [aid for aid, v in approvals.items() if v]
    st.metric("Actions approved", len(approved_ids))

    if not approved_ids:
        st.warning("Approve at least one action above.")
        return

    col_dry, col_live = st.columns(2)
    if col_dry.button("🧪 Dry Run", use_container_width=True):
        _execute(selected_path, approved_ids, dry_run=True)

    col_live.warning("Live execution modifies GCP resources.")
    if col_live.button("🚀 Execute Live", type="primary", use_container_width=True):
        _execute(selected_path, approved_ids, dry_run=False)


def _execute(actions_path: Path, approved_ids: list[str], dry_run: bool) -> None:
    mode = "Dry Run" if dry_run else "LIVE"
    cmd = [
        sys.executable, "web_runner.py",
        "--actions-file", str(actions_path),
        "--approved-ids", ",".join(approved_ids),
    ]
    if dry_run:
        cmd.append("--dry-run")

    with st.spinner(f"Executing ({mode})…"):
        ok, output = run_subprocess(cmd, timeout=300)

    # Parse JSON result
    results = []
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("["):
            try:
                results = json.loads(line)
                break
            except Exception:
                pass

    if results:
        st.subheader("Results")
        for item in results:
            title  = item.get("title", item.get("id", ""))
            status = item.get("status", "")
            result = item.get("result", "")
            if status == "succeeded":
                st.success(f"✅ **{title}**  \n{result}")
            elif status == "failed":
                st.error(f"❌ **{title}**  \n{result}")
            elif "dry" in status or (result and "DRY RUN" in result.upper()):
                st.info(f"🧪 **{title}**  \n{result}")
            elif status == "rejected":
                st.warning(f"⏭️ **{title}** — not approved")
            else:
                st.write(f"• **{title}** — {status}: {result}")
    elif ok:
        st.success(f"Execution ({mode}) complete.")
        with st.expander("Output"):
            st.code(output, language="text")
    else:
        st.error(f"Execution ({mode}) failed.")
        with st.expander("Output", expanded=True):
            st.code(output, language="text")


# ── Page: Phase 3 ─────────────────────────────────────────────────────────────
def page_autonomous() -> None:
    st.header("🤖 Phase 3 — Autonomous")
    st.markdown(
        "Policy-based auto-approval. Each proposed action is evaluated against "
        "`policies/default.yaml` and approved or flagged for human review."
    )

    st.subheader("Active Policy Rules")
    if POLICIES_FILE.exists():
        try:
            policy = yaml.safe_load(POLICIES_FILE.read_text())
            rules  = policy.get("rules", [])
            default_dec = policy.get("default", "require_human")
            st.caption(f"Default (no rule matches): **{default_dec}**")

            for i, rule in enumerate(rules, 1):
                decision = rule.get("decision", "require_human")
                name = rule.get("name", f"Rule {i}")
                desc = rule.get("description", "")
                if decision == "auto_approve":
                    badge = "🟢 auto_approve"
                elif decision == "require_human":
                    badge = "🟡 require_human"
                else:
                    badge = "🔴 auto_reject"

                conds = []
                for field in ("action_types", "blast_radius", "reversibility", "categories", "severities"):
                    val = rule.get(field)
                    if val:
                        conds.append(f"`{field}`: {val}")

                with st.expander(f"**{i}.** {badge} — `{name}`"):
                    if desc:
                        st.write(desc)
                    for cond in conds:
                        st.markdown(f"- {cond}")
                    if not conds:
                        st.caption("Matches all actions.")
        except Exception as e:
            st.error(f"Could not parse policy file: {e}")
            st.code(POLICIES_FILE.read_text(), language="yaml")
    else:
        st.warning(f"Policy file not found: `{POLICIES_FILE}`")

    st.divider()
    st.subheader("Run Phase 3")
    col_dry, col_live = st.columns(2)

    if col_dry.button("🧪 Phase 3 Dry Run", type="primary", use_container_width=True):
        with st.spinner("Running Phase 3 dry run — this may take 3–6 minutes…"):
            ok, output = run_subprocess(
                [sys.executable, "main.py", "--phase", "3", "--dry-run"], timeout=600
            )
        if ok:
            st.success("Phase 3 dry run complete!")
        else:
            st.error("Phase 3 encountered errors.")
        with st.expander("Output", expanded=True):
            st.code(output or "(no output)", language="text")
        st.rerun()

    col_live.warning("Live Phase 3 will make real GCP changes via the policy engine.")
    if col_live.button("🚀 Phase 3 Live", use_container_width=True):
        with st.spinner("Running Phase 3 live — this may take 3–6 minutes…"):
            ok, output = run_subprocess(
                [sys.executable, "main.py", "--phase", "3"], timeout=600
            )
        if ok:
            st.success("Phase 3 live run complete!")
        else:
            st.error("Phase 3 encountered errors.")
        with st.expander("Output", expanded=True):
            st.code(output or "(no output)", language="text")
        st.rerun()


# ── Page: Phase 4 ─────────────────────────────────────────────────────────────
def page_finops() -> None:
    st.header("💸 Phase 4 — FinOps Agent")
    st.caption("🚧  This phase is currently in development. Early access pilots launching soon.")

    st.markdown(
        "A dedicated cost intelligence layer that goes beyond flagging idle resources. "
        "The FinOps Agent continuously monitors spend across your entire GCP organisation, "
        "identifies waste with resource-level precision, and acts on it — automatically."
    )

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        with st.expander("💰 Committed Use Discount Analysis", expanded=True):
            st.markdown("""
Identifies workloads that are running on-demand but qualify for 1-year or 3-year
Committed Use Discounts (CUDs).

- Analyses 90-day usage patterns per machine family and region
- Calculates projected annual savings before recommending any commitment
- Flags workloads where CUD commitment confidence is above 85%
- Never recommends a commitment it cannot justify with usage data

**Typical savings: 37–55% on qualifying compute spend**
            """)

        with st.expander("📐 Right-Sizing with Confidence Scores", expanded=True):
            st.markdown("""
Cross-references 30 days of CPU, memory, and network utilisation to recommend
the smallest machine type that will not degrade performance.

- Each recommendation carries a confidence percentage
- Accounts for burst patterns, not just averages
- Groups recommendations by team / label for easy handoff
- Generates a ready-to-execute resize plan

**Typical savings: $8,000–$40,000/year per mid-size environment**
            """)

        with st.expander("🚨 Cost Anomaly Detection", expanded=True):
            st.markdown("""
Establishes a rolling 14-day spend baseline per service and per region.

- Flags deviations above configurable thresholds (default: 20%)
- Distinguishes planned growth from unexpected spikes
- Surfaces anomalies before they appear on the billing invoice
- Auto-correlates anomalies with recent deployments or config changes
            """)

    with c2:
        with st.expander("🔔 Budget Alert Gap Detection", expanded=True):
            st.markdown("""
Scans every project and every service for missing or misconfigured budget alerts.

- Identifies projects with zero budget alerts configured
- Detects alerts set above realistic thresholds (e.g. $1M on a $5k/month project)
- Configures alerts automatically at sensible default thresholds
- Ensures every billing account has at least one alert at 80%, 100%, and 120%
            """)

        with st.expander("🗺️ Cross-Project Spend Consolidation", expanded=True):
            st.markdown("""
For organisations running multiple GCP projects, maps total spend across all
projects and surfaces which team, service, or environment is driving growth.

- Aggregates spend by label (team, env, service)
- Generates a weekly cost attribution report
- Highlights the top 5 fastest-growing cost centres
- Compares month-over-month and quarter-over-quarter trends
            """)

        with st.expander("🧹 Idle Resource Cleanup Engine", expanded=True):
            st.markdown("""
Goes beyond detecting idle resources — it schedules and executes cleanup.

- Identifies VMs, disks, IPs, and load balancers with zero utilisation
- Applies a configurable grace period before marking for deletion
- Sends a notification (email / Slack) to the resource owner before acting
- Maintains a full audit trail of every resource removed and cost recovered
            """)

    st.divider()
    st.success(
        "**Interested in early access?** Phase 4 pilot programme is open. "
        "Connect your GCP project and get a full FinOps report within 24 hours."
    )
    st.markdown("📩  Reach out via LinkedIn or email to join the waitlist.")


# ── Page: Phase 5 ─────────────────────────────────────────────────────────────
def page_rca() -> None:
    st.header("🧠 Phase 5 — Root Cause Analysis Agent")
    st.caption("🚧  This phase is currently in development. Early access pilots launching soon.")

    st.markdown(
        "Autonomous incident investigation that starts working the moment something breaks — "
        "before an engineer even joins the call. The RCA Agent eliminates the first 45 minutes "
        "of manual log trawling from every incident."
    )

    st.divider()

    st.subheader("What Happens in the First 90 Seconds of an Incident")
    steps = [
        ("1️⃣  Log Correlation",
         "Pulls error logs across all affected services for the preceding 6 hours. "
         "Identifies the **first error timestamp** and traces it forward through every dependent service "
         "to map the full blast radius of the failure."),
        ("2️⃣  Deployment Correlation",
         "Checks whether a code release, config change, or infrastructure event occurred in the "
         "preceding 4 hours. Automatically links the most likely change to the incident timeline "
         "and surfaces the exact diff or deployment ID."),
        ("3️⃣  Infrastructure Change Detection",
         "Scans for autoscaler events, node replacements, quota limit hits, certificate expirations, "
         "and network route changes that coincide with the incident window."),
        ("4️⃣  External Signal Correlation",
         "Cross-references the GCP service health dashboard, Cloud Monitoring alerts, and uptime "
         "check results to rule out platform-level causes before investigating application code."),
        ("5️⃣  Structured RCA Report",
         "Produces a timestamped, shareable incident report: **Timeline → Root Cause → Blast Radius "
         "→ Recommended Fix**. Ready to paste into a postmortem or stakeholder update within 90 seconds."),
    ]
    for title, body in steps:
        with st.expander(title, expanded=True):
            st.markdown(body)

    st.divider()
    st.subheader("Key Capabilities")

    c1, c2, c3 = st.columns(3)
    c1.metric("MTTR Reduction", "~60%", help="Average reduction in mean time to resolution across pilot environments")
    c2.metric("Time Saved per Incident", "45 min", help="Average time eliminated from the initial investigation phase")
    c3.metric("Auto-Resolved Incidents", "~35%", help="Incidents where the RCA agent identifies and fixes the root cause without human intervention")

    st.divider()
    st.subheader("How It Integrates")
    st.markdown("""
| Trigger | What happens |
|---|---|
| Cloud Monitoring alert fires | RCA agent starts immediately, no human action needed |
| Error rate spike detected in Phase 1 scan | Automatically escalates to RCA agent |
| Manual trigger from this UI | On-demand investigation of any time window |
| Scheduled postmortem review | Weekly summary of all incidents, patterns, and repeat root causes |
    """)

    st.divider()
    st.success(
        "**Interested in early access?** Phase 5 pilot programme is open. "
        "Ideal for teams running GCP in production with on-call responsibilities."
    )
    st.markdown("📩  Reach out via LinkedIn or email to join the waitlist.")


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    page = render_sidebar()
    if page == "🏠 Overview":
        page_overview()
    elif page == "🔍 Phase 1 — Scan":
        page_scan()
    elif page == "⚡ Phase 2 — Actions":
        page_actions()
    elif page == "🤖 Phase 3 — Autonomous":
        page_autonomous()
    elif "Phase 4" in page:
        page_finops()
    elif "Phase 5" in page:
        page_rca()


if __name__ == "__main__":
    main()
