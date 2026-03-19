# Cloud Ops AI Agent — Client Demo Script

**Platform URL:** https://cloud-ops-streamlit-974082774877.us-central1.run.app
**Demo Company:** Northstar Logistics (fictional)
**Demo Duration:** 20–30 minutes
**Format:** Screen share + live walkthrough

---

## Before You Start (Setup — 2 minutes before the call)

1. Open the URL in Chrome, full screen
2. Click **"🎯 Load Demo Data"** in the sidebar
3. Confirm the sidebar shows **"DEMO MODE ACTIVE — northstar-prod-001"**
4. You should see metrics populated on the Overview page
5. Have this script open on a second monitor

---

## Opening Hook (2 minutes)

> "Before I show you the platform, let me ask you a quick question. How do you currently know if your GCP environment has a misconfigured firewall? Or if a service account has more permissions than it should? Or if you're paying $2,000 a month for idle infrastructure you forgot about?"

*[Pause for response]*

> "Most teams find out either through a quarterly security review, a surprise cloud bill, or worse — an incident. What we've built is a system that continuously watches your entire GCP environment across five dimensions — security, infrastructure, cost, incidents, and deployments — and not just flags issues but proposes and executes fixes. Let me show you."

---

## Part 1 — Overview Page (4 minutes)

*You should be on the Overview page. Point to the metrics at the top.*

> "This is your GCP environment health dashboard. Right now we're looking at a demo environment for Northstar Logistics — a mid-size logistics company. The platform has just completed a full scan."

**Point to the severity breakdown:**
> "6 Critical findings. 8 High. In real terms: there are 6 things in this environment right now that an attacker could exploit or that could cause an outage today — not next week, today."

**Point to the agent breakdown (by_agent):**
> "These findings come from 5 specialised AI agents running in parallel. Each one has deep domain knowledge:
> - The Security Agent is checking IAM, firewall rules, service account permissions, exposed APIs
> - The Infrastructure Agent is looking at Kubernetes versions, VPC design, database configs
> - The Cost Agent is finding idle resources, unoptimised billing, missed discounts
> - The Incident Agent is checking whether you'd even *know* if something went wrong — alerting, monitoring, log retention
> - The Deployment Agent is looking at how your services are configured to run"

> "They all run simultaneously and finish in under 3 minutes for most GCP projects."

---

## Part 2 — Phase 1: Scan Page (6 minutes)

*Click "Phase 1 — Scan" in the sidebar*

> "This is where a scan is triggered and results are browsed. For this demo the scan has already run. Let me walk you through some of the findings."

**Filter to Critical first:**

> "Let me filter to Critical findings only."

*Set the severity filter to "critical"*

**Finding 1 — Cloud SQL publicly accessible:**
> "This is arguably the scariest one. Northstar's production orders database — containing customer PII and payment transaction records — has an authorised network of 0.0.0.0/0. That means the database port is open to the entire internet. Anyone with valid credentials or a SQL injection vulnerability has direct network access. This is a P0 incident waiting to happen."

**Finding 2 — orders-api 2,847 errors with no alerts:**
> "The production checkout API had nearly 3,000 errors in the last 24 hours — a 14% error rate. Customers are experiencing failed checkouts right now. And because there are zero alerting policies configured, no engineer has been paged. The team would only find out via customer complaints."

**Finding 3 — Service account with Editor role:**
> "The nightly ETL pipeline runs as a service account with project-level Editor access. That's near-full access to every resource in the project. If that pipeline is ever compromised, the attacker inherits access to everything."

*Now filter to High — show the cost findings*

**Finding — Idle GKE node pools, $2,340/month:**
> "Three GKE node pools have had zero activity for 14 days. They're running 9 VMs 24/7 for no reason. That's $2,340 a month — $28,000 a year — in pure waste. The platform identified this automatically, no manual review needed."

**Finding — Dev database in production, $890/month:**
> "There's a development database running in the production project, always on, despite being used only during business hours. Another $890/month that can be eliminated with a simple start/stop schedule."

> "And these are just the highlights. 30 findings total. A human security engineer doing a manual review would take days to produce this. We did it in under 3 minutes."

---

## Part 3 — Phase 2: Actions Page (7 minutes)

*Click "Phase 2 — Actions" in the sidebar*

> "Finding problems is only half the value. This is where the platform goes further. Phase 2 takes every finding and generates a specific, executable remediation — not a generic recommendation, a real GCP API call with rollback instructions."

**Point to the executed actions (status: approved + outcome shows SUCCESS):**

> "Look at these two — already done. The platform proposed disabling the RDP firewall rule. An engineer reviewed it, approved it, and it executed in 15 seconds. The platform verified the change and logged the outcome. The firewall rule is gone."

> "Same for the SSH rule — it's now restricted to the IAP proxy range, which means SSH access only works through Google's Identity-Aware Proxy with full audit logging. That's a significant security improvement that would normally require a change request, a ticket, a change window. Done in 30 seconds."

**Point to approved actions awaiting execution:**

> "These two are approved but haven't executed yet — they're queued. Removing the Editor role from the data pipeline service account, and enabling versioning on the backup buckets."

**Point to pending actions:**

> "These three are waiting for human approval. The GKE autoscaler config, the dev database schedule, the analytics backup config. The platform proposes them, a human decides. This is important — the platform never executes something the team hasn't reviewed."

**Point to skipped actions:**

> "And these three were deliberately skipped by the team. Deleting the orphaned disk is irreversible — the data owner wanted to confirm first. The contractor access removal is pending HR sign-off. The ICMP rule change is being bundled into a broader VPC migration. The platform respects those decisions."

> "Every action has a blast radius rating, a reversibility label, and step-by-step rollback instructions. Engineers don't have to trust a black box — they can see exactly what will run and how to undo it."

---

## Part 4 — Phase 3: Autonomous Page (5 minutes)

*Click "Phase 3 — Autonomous" in the sidebar*

> "Phase 3 is where this becomes genuinely powerful for operations teams. This is policy-driven autonomous execution."

**Point to the policy rules:**

> "The platform has a policy file that defines which types of actions it's allowed to execute autonomously — without human approval — and which ones always require a human. For example: reversible, low blast-radius security fixes can auto-execute. Anything irreversible, or anything touching IAM, requires a human."

> "So if a new scan runs tomorrow and finds another wide-open firewall rule, it gets fixed automatically — no ticket, no Slack message, no engineer interrupted at 2am. But if it finds something that would delete data or modify IAM policies, it parks it for human review."

> "This is the difference between a reporting tool and an autonomous operations agent."

---

## Part 5 — Multi-Customer / Your GCP Project (3 minutes)

*Click the "🔧 Switch GCP Project" expander in the sidebar*

> "One more thing I want to show you. This platform is not specific to this demo environment. It connects to *your* GCP project."

> "All you need is a GCP service account JSON key with read access to your project. You upload it here, enter your Project ID, click Apply — and every scan, every finding, every action proposal is against your actual infrastructure."

> "We can do that right now if you want. Or we can walk through what the service account setup looks like — it's a 10-minute task."

*[If client is interested, offer to run a live scan against their project on the spot]*

---

## Handling Common Questions

**"What GCP permissions does the service account need?"**
> "We need read-only roles for the scan: Viewer, Security Reviewer, Cloud Asset Viewer, Monitoring Viewer, and Billing Account Viewer. For Phase 3 execution, we add specific write roles only for the action types you want automated. You control exactly what the platform can touch."

**"Where is our data stored? Is it leaving our GCP environment?"**
> "Scan findings are stored in JSON files within the platform's Cloud Run container, scoped to your session. No data is sent to third parties. All GCP API calls go directly from the platform to your GCP project using your service account credentials."

**"What if it executes something that breaks our environment?"**
> "Every action has rollback instructions built in. Reversible actions can be undone with a single gcloud command. The platform flags irreversible actions explicitly and requires human approval for them. We also recommend starting in a non-production project to build confidence before running Phase 3 on production."

**"Can this integrate with our existing tools — PagerDuty, Jira, Slack?"**
> "That's Phase 4 — on the roadmap. The findings and action outcomes are structured JSON that can be pushed to any webhook, ticketing system, or notification channel. The integration layer is straightforward to build on top of what's here."

**"How often does it scan?"**
> "Currently on-demand trigger from the UI. Scheduled recurring scans (every 6 hours, daily) are a configuration option we can enable — it's a Cloud Scheduler job pointing at the same scan endpoint."

**"What does pricing look like?"**
> "The platform runs on your own GCP infrastructure — you pay GCP for the Cloud Run and Cloud Build compute, which for typical usage is under $20/month. Our engagement covers setup, customisation of the policy file to your environment, and ongoing support. Happy to put together a proposal based on your project size and the scope of automation you want."

---

## Closing (2 minutes)

> "To summarise what you've seen today:
> - Phase 1 scanned a full GCP environment and surfaced 30 findings across security, cost, infrastructure, monitoring, and deployments — in under 3 minutes
> - Phase 2 generated specific, executable remediation actions with blast radius ratings and rollback instructions — no vague recommendations
> - Phase 3 can automatically fix the low-risk, reversible issues the moment they appear, without a human in the loop
> - And the whole thing connects to your specific GCP project in under 5 minutes"

> "The question isn't whether your GCP environment has issues like these. Every environment does. The question is whether you find them before an attacker does — or before your cloud bill does."

> "What would be most useful next — running a scan against your actual environment today, or walking through the service account setup?"

---

## Post-Demo Next Steps

- [ ] Share the platform URL with the client
- [ ] Send the service account setup instructions (5-minute guide)
- [ ] Offer a live scan of their non-production project as a proof of value
- [ ] Follow up with a proposal within 48 hours
