# Culprit — OpenAI Build Week 2026 Build Guide

**One-liner:** An AI agent that investigates production incidents like a senior SRE — it reconstructs the timeline from logs, metrics, and deploy history, identifies the likely root-cause commit, and drafts an evidence-linked postmortem in minutes instead of days.

**Hackathon:** OpenAI Build Week (Jul 13–21, 2026) · Solo build · $100K prize pool
**Deadline:** July 21, 5:00 PM PT

---

## 0. Project Details

### Overview

Culprit is an autonomous incident-investigation system for engineering teams. When a production outage occurs, the agent connects to the team's existing observability and code infrastructure — Prometheus metrics, Loki logs, Grafana alerts, and GitHub commit/deploy history — and conducts a structured investigation the way a senior SRE would: it establishes the incident window from metric anomalies, correlates it with recent deploys, pulls and reads the actual code diffs, generates competing root-cause hypotheses, and then actively tries to *disprove* each hypothesis with follow-up queries before committing to a conclusion.

The output is not a chat answer. It is a complete incident record: an interactive timeline of what happened, a ranked set of hypotheses with confidence scores, the suspect commit with the failure mechanism explained line-by-line, and a publishable blameless postmortem — where every single claim is hyperlinked to the raw evidence (a specific log cluster, metric query, or diff) that supports it. Engineers can watch the investigation unfold live through a streaming "agent feed," then review, edit, and export the postmortem in minutes.

GPT-5.6 powers the entire reasoning core: investigation planning, tool orchestration across four external APIs, hypothesis generation and self-verification, and structured report synthesis.

### The Problem

When production breaks, fixing it is only half the pain. Afterward, someone has to answer *why* — and that process is slow, manual, and universally dreaded:

- **Evidence is scattered across disconnected systems.** The metrics live in Prometheus, the logs in Loki, the deploys in GitHub, the alerts in Grafana. Root-causing means manually cross-referencing timestamps across four browser tabs, often at 3 AM or in the exhausted aftermath.
- **It consumes senior engineering time.** Root-cause analysis can't be delegated to juniors — it requires someone who understands the system deeply. Post-incident reviews routinely consume hours to days of the most expensive engineers on the team, per incident.
- **Postmortems get skipped or hollowed out.** Because the process is so painful, many incidents never get a real postmortem — or get a rushed one with "root cause: bad deploy, action item: be more careful." The organization loses the learning, and the same class of failure recurs.
- **Slow diagnosis extends outages.** The same evidence-correlation work needed for the postmortem is needed *during* the incident to find what to roll back. Every minute of manual log archaeology is a minute of downtime, and downtime is measured in thousands of dollars per minute for many businesses.
- **Existing tools coordinate; they don't investigate.** Incident-management platforms (incident.io, Rootly, FireHydrant) excel at paging, Slack channels, and status pages — but the actual analytical work of connecting a latency spike to line 42 of a specific commit is still done entirely by hand.

### The Solution in One Sentence

An agent that does the log archaeology, timeline reconstruction, and git-blame detective work autonomously — with verifiable, evidence-linked conclusions — so engineers confirm findings instead of hunting for them.

### Target Users

- **Primary:** SRE/platform/DevOps engineers at teams running Grafana-stack observability with GitHub-based deploys (a very large, self-serve-reachable install base).
- **Secondary:** Engineering managers who need consistent, high-quality postmortems for compliance, customer RCAs, and organizational learning.

---

## 1. Why This Can Win (Judging Criteria Mapping)

| Criterion | How this project scores |
|---|---|
| **Technological Implementation** | Multi-step agentic pipeline: GPT-5.6 plans an investigation, calls tools (GitHub, Grafana, Loki), forms hypotheses, tests them against evidence, and self-corrects. Not a chat wrapper. |
| **Design** | Complete product loop: incident triggers → agent investigates → interactive dashboard shows timeline, evidence, root cause, and a publishable postmortem. |
| **Potential Impact** | Postmortems are mandatory at every serious eng org and universally hated. Downtime costs are measured in $/minute; MTTR reduction is a quantifiable ROI story. |
| **Quality of Idea** | Root-cause *synthesis* across heterogeneous signals (code diffs + logs + metrics) is genuinely non-obvious. Incident.io/Rootly do coordination, not autonomous investigation. |

**Solo-builder survival rule:** One polished end-to-end flow beats five half-features. Everything below is scoped to that.

---

## 2. Product Scope (MVP — what you demo)

**In scope:**
1. Connect a GitHub repo (deploy/commit history via GitHub API).
2. Connect Grafana stack (Prometheus for metrics, Loki for logs) running a small demo service you deploy yourself.
3. "Investigate" button (or webhook trigger) starts the agent.
4. Agent output: interactive incident timeline, ranked root-cause hypotheses with evidence links, suspect commit with diff highlights, draft postmortem (blameless format) exportable as Markdown.
5. Live "agent thinking" feed — stream the agent's investigation steps to the UI. **This is your demo wow-factor.**

**Out of scope (say no):** auth/multi-tenant, Slack bot, PagerDuty integration, multiple incident types, fine-tuning, mobile.

**Demo strategy for "real integrations":** You chose real integrations — the trick is to make the *infrastructure* real but the *incident* controlled. Deploy a small real microservice (e.g., a FastAPI "orders" service) with Prometheus + Loki + Grafana via docker-compose, then push a genuinely bad commit (e.g., an N+1 query or a broken timeout config) and let real errors flow. The agent investigates a real system, but you control the script. Keep a recorded backup demo video in case live infra misbehaves during judging.

---

## 3. Tech Stack

### Backend
- **Python 3.12 + FastAPI** — API server + agent orchestration
- **OpenAI Python SDK** — GPT-5.6 with tool calling (the hackathon requires GPT-5.6; use Codex as your coding assistant throughout)
- **httpx** — async calls to GitHub / Prometheus / Loki APIs
- **SSE (Server-Sent Events)** via `sse-starlette` — stream agent steps to the UI
- **SQLite + SQLModel** — persist incidents, investigation runs, findings (zero-ops DB, perfect for a demo)
- **Pydantic v2** — structured outputs from the model (hypotheses, timeline events, postmortem schema)

### Frontend
- **React 18 + Vite + TypeScript**
- **TailwindCSS** (+ shadcn/ui for polished components fast)
- **Recharts** — metric charts on the timeline
- **react-markdown** — render the postmortem
- **EventSource API** — consume the SSE agent stream

### Integrations (real)
- **GitHub REST API** — commits, diffs, deployments (PAT auth; use your own demo repo)
- **Prometheus HTTP API** — `query_range` for metric anomalies (error rate, latency, CPU)
- **Loki HTTP API** — `query_range` LogQL for error logs around the incident window
- **Grafana** — human-viewable dashboards (nice B-roll for the demo video)

### Demo Infra
- **docker-compose**: demo microservice + Prometheus + Loki + Promtail + Grafana + a load generator (`locust` or a simple looped `httpx` script)

### Deployment (optional but impressive)
- Backend + demo stack on a cheap VPS (Hetzner/DigitalOcean) or Fly.io; frontend on Vercel. Local docker-compose is acceptable for the video.

---

## 4. Architecture

```
┌─────────────┐     SSE stream      ┌──────────────────────┐
│ React + Vite │ ◄────────────────── │  FastAPI backend      │
│  Dashboard   │ ──── REST ────────► │                      │
└─────────────┘                     │  ┌────────────────┐  │
                                    │  │ Agent Orchestr. │  │
                                    │  │  (GPT-5.6 loop) │  │
                                    │  └───┬────────────┘  │
                                    │      │ tool calls     │
                                    │  ┌───▼────────────┐  │
                                    │  │ Tool layer      │  │
                                    │  └─┬────┬────┬────┘  │
                                    └────┼────┼────┼───────┘
                                         │    │    │
                                   GitHub  Prometheus  Loki
                                    API      API       API
```

### Agent design (the core IP)

A **plan → gather → hypothesize → verify → report** loop:

1. **Triage:** Given the incident window (alert time or user-supplied), pull top-level signals: error-rate spike shape, affected endpoints.
2. **Evidence gathering (tool calls):**
   - `get_recent_commits(window)` → commits/deploys near incident start
   - `query_metrics(promql, range)` → error rate, latency p95, saturation
   - `query_logs(logql, range)` → error clusters, stack traces
   - `get_commit_diff(sha)` → inspect suspect changes
3. **Hypothesis generation:** Model produces 2–4 ranked hypotheses as structured JSON (`cause`, `confidence`, `supporting_evidence[]`, `disconfirming_test`).
4. **Verification loop:** For each hypothesis, the agent runs its own `disconfirming_test` (another metric/log query) and updates confidence. **This self-verification step is what makes judges say "non-trivial."**
5. **Report:** Structured output → timeline events + postmortem draft (summary, impact, root cause, contributing factors, action items), every claim linked to an evidence artifact ID.

Persist every tool call + result as an `EvidenceArtifact` row so the UI can deep-link claims → raw evidence.

---

## 5. 8-Day Plan with Build Prompts

Use these prompts with Codex (or GPT-5.6 in your IDE). They're written to be pasted nearly as-is; adjust paths/names. Commit at the end of every prompt block — judges may look at commit history for genuine effort.

### Day 1 (Jul 13) — Skeleton + demo infrastructure

**Prompt 1.1 — Repo scaffold**
> Create a monorepo with `/backend` (FastAPI, Python 3.12, uv for dependency management) and `/frontend` (React 18 + Vite + TypeScript + TailwindCSS + shadcn/ui). Backend should have a `/health` endpoint and CORS configured for the Vite dev server. Add a root README, .gitignore, and a Makefile with `make dev` that runs both. Use SQLModel with SQLite at `backend/data/app.db`.

**Prompt 1.2 — Demo microservice + observability stack**
> Create `/demo-stack` with docker-compose running: (1) a FastAPI "orders" microservice with endpoints `/orders`, `/orders/{id}`, `/checkout` that talks to a Postgres container, instrumented with prometheus-fastapi-instrumentator and structured JSON logging to stdout; (2) Prometheus scraping it; (3) Loki + Promtail collecting its container logs; (4) Grafana provisioned with a dashboard showing request rate, error rate, and p95 latency; (5) a `loadgen` container that continuously sends realistic traffic with httpx. Document how to start everything in the README.

**Prompt 1.3 — The breakable commit**
> In the orders service, create a git branch `incident/n-plus-one` containing a subtle bug: change the `/orders` handler to run one SQL query per order item instead of a join, and lower the DB connection pool from 20 to 3. Under load this should cause latency spikes and connection-pool timeout errors. Write a `scripts/trigger_incident.sh` that merges and redeploys this, and `scripts/resolve_incident.sh` that reverts it.

**End of day check:** `docker compose up` → Grafana shows healthy traffic → run trigger script → error rate visibly spikes and Loki shows timeout errors.

### Day 2 (Jul 14) — Tool layer (real integrations)

**Prompt 2.1 — GitHub tools**
> In `backend/app/tools/github.py`, implement an async GitHubClient (httpx, PAT from env) with: `list_commits(repo, since, until)` returning sha, author, message, timestamp, changed files; `get_commit_diff(repo, sha)` returning the unified diff truncated to 8000 chars with a note if truncated; `list_deployments(repo, since)`. Add retry with backoff and a thin caching layer (SQLite table keyed by request hash) so repeated agent runs don't burn rate limits. Write pytest tests using respx mocks.

**Prompt 2.2 — Prometheus + Loki tools**
> In `backend/app/tools/metrics.py` implement `query_range(promql, start, end, step)` against the Prometheus HTTP API, returning downsampled series (max 100 points) plus computed summary stats (min/max/mean, spike detection via z-score > 3). In `backend/app/tools/logs.py` implement `query_logs(logql, start, end, limit)` against Loki, plus `cluster_errors(entries)` that groups similar error messages by normalized template (strip numbers/ids) and returns top clusters with counts and 2 sample lines each. Summarization matters: raw output must be compact enough to feed an LLM.

**Prompt 2.3 — Evidence store**
> Create SQLModel models: `Incident(id, title, started_at, window_start, window_end, status)`, `InvestigationRun(id, incident_id, status, created_at)`, `EvidenceArtifact(id, run_id, tool_name, input_json, output_json, summary, created_at)`, `Finding(id, run_id, kind, content_json, confidence, evidence_ids)`. Every tool call made during a run must be persisted as an EvidenceArtifact. Add CRUD endpoints: POST /incidents, GET /incidents/{id}, GET /runs/{id}/artifacts.

### Day 3 (Jul 15) — Agent core

**Prompt 3.1 — Orchestrator loop**
> In `backend/app/agent/orchestrator.py`, build an investigation agent using the OpenAI SDK with GPT-5.6 and native tool calling. Tools: get_recent_commits, get_commit_diff, list_deployments, query_metrics, query_logs, cluster_errors. The loop: (1) system prompt establishes the SRE-investigator persona and the plan→gather→hypothesize→verify→report method; (2) run up to 25 tool-call iterations; (3) each tool result is persisted as an EvidenceArtifact and its DB id is injected back into the conversation so the model can cite artifact ids; (4) the run ends when the model calls a `submit_report` tool with a structured payload. Emit an async event (for SSE) for every step: plan updates, tool calls, tool summaries, hypothesis changes.

**Prompt 3.2 — Structured outputs**
> Define Pydantic schemas for the `submit_report` tool: `TimelineEvent(ts, title, description, evidence_ids)`, `Hypothesis(cause, mechanism, confidence_0_to_1, supporting_evidence_ids, disconfirming_test_description, verification_result)`, `Postmortem(summary, impact, root_cause, contributing_factors, detection_gaps, action_items[])`, all wrapped in `InvestigationReport`. Enforce with OpenAI structured outputs / strict tool schemas. Reject and re-ask (max 2 retries) if evidence_ids reference nonexistent artifacts.

**Prompt 3.3 — System prompt (write this one yourself, iterate hard)**
Key elements to include:
> You are an expert SRE investigating a production incident. Method: (1) Establish the incident window from metrics before anything else. (2) Correlate deploy/commit timing with the anomaly onset — timing correlation is a lead, not proof. (3) Generate 2–4 competing hypotheses; for each, state what evidence would DISPROVE it, then run that query. (4) Only assign confidence > 0.8 if you inspected the actual code diff and it mechanistically explains the observed errors. (5) Cite artifact ids for every claim. Prefer fewer, verified claims over exhaustive speculation. Blameless language only.

**End of day check:** Trigger the incident, run the agent from a curl call, and get a coherent JSON report identifying the N+1 commit.

### Day 4 (Jul 16) — Streaming + dashboard skeleton

**Prompt 4.1 — SSE endpoint**
> Add `GET /runs/{id}/stream` using sse-starlette that streams agent events (step_started, tool_call, tool_result_summary, hypothesis_update, report_ready) as JSON. Back it with an asyncio queue per run. Include replay of already-emitted events on reconnect so a page refresh doesn't lose the feed.

**Prompt 4.2 — Dashboard shell**
> In the frontend, build with shadcn/ui + Tailwind: (1) Incidents list page; (2) Incident detail page with three panels — left: live "Investigation Feed" consuming the SSE stream, rendered as a vertical step timeline with icons per tool; center: incident timeline + metric chart (Recharts) with the incident window shaded and deploy markers; right: tabbed panel for Hypotheses / Postmortem / Evidence. Dark theme, dense-but-clean SRE aesthetic. Add a prominent "Investigate" button that POSTs to start a run.

### Day 5 (Jul 17) — The money screens

**Prompt 5.1 — Hypotheses UI**
> Build the Hypotheses tab: ranked cards showing cause, confidence as a bar, mechanism explanation, and chips for each supporting evidence artifact. Clicking an evidence chip opens a drawer showing the raw artifact (diff rendered with react-diff-viewer, log clusters as a table, metric queries as a mini chart). Show the disconfirming test the agent ran and its verdict (confirmed/weakened) with a visual badge.

**Prompt 5.2 — Postmortem view + export**
> Build the Postmortem tab: rendered markdown of the generated postmortem with inline evidence citations as superscript links into the evidence drawer. Add "Copy as Markdown" and "Download .md" buttons. Add an action-items checklist with owner placeholders.

**Prompt 5.3 — Suspect commit spotlight**
> Add a "Root Cause" hero card at the top of the incident page once a run completes: commit sha, author (avatar via GitHub), message, time-to-incident delta, and the 5 most damning diff lines highlighted with the agent's one-sentence explanation of the failure mechanism.

### Day 6 (Jul 18) — Hardening + second incident type

**Prompt 6.1 — Second scenario**
> Add a second incident branch `incident/bad-timeout`: set the orders service's downstream HTTP client timeout to 100ms, causing intermittent 502s under normal latency variance. Verify the agent correctly distinguishes this from the N+1 scenario. Fix any prompt/tool weaknesses discovered.

(Two different incidents, correctly diagnosed, is your proof this isn't hard-coded.)

**Prompt 6.2 — Failure handling**
> Add graceful degradation: tool-call timeouts surface as feed events and the agent is told to proceed with partial evidence; a run-level watchdog kills runs after 5 minutes and salvages a partial report; token budget guardrails summarize the conversation when it exceeds a threshold. Add a global error boundary + retry in the frontend.

**Prompt 6.3 — Webhook trigger (nice-to-have)**
> Add POST /webhooks/alertmanager that accepts a Grafana/Alertmanager alert payload and auto-creates an incident + starts an investigation. Wire a real alert rule (error rate > 5% for 2m) in the demo stack. Demo line: "no human even clicked Investigate."

### Day 7 (Jul 19) — Polish + deploy

- Deploy backend + demo stack to a VPS, frontend to Vercel. Test end-to-end remotely.
- Visual pass: loading states, empty states, favicon, product name + logo (pick a name — e.g., "Autopsy", "RootCause", "Postmortem.dev").
- Seed the deployed app with one completed investigation so judges landing on it see a finished result immediately.
- Write the README as a mini pitch: problem, demo GIF, architecture diagram, how GPT-5.6 is used (be explicit — judges score this).

### Day 8 (Jul 20–21) — Demo video + submission

**Video script (≤3 min):**
1. (20s) Hook: "Every outage ends with the worst part: the postmortem. Hours of log archaeology and git blame." Show a chaotic Grafana dashboard.
2. (20s) Trigger the incident live — error rate spikes.
3. (60s) Click Investigate. Let the live agent feed run — narrate what it's doing ("it noticed the spike started 4 minutes after a deploy… now it's pulling the diff… now it's running a query to disprove its own hypothesis").
4. (40s) Root-cause card + evidence drill-down + postmortem export.
5. (20s) Second incident type in fast-forward — proves generality.
6. (20s) Business close: MTTR cost math, who pays, what's next.

Submit by **July 21, 5:00 PM PT** — aim for the morning, not the deadline.

---

## 6. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Agent gives vague/wrong root cause | Verification loop + "inspect the diff before confidence > 0.8" rule; test on both scenarios daily |
| Live demo infra fails during judging | Pre-recorded video is primary artifact; seed a completed run in the deployed app |
| Token/context blowup from raw logs | Summarize/cluster in the tool layer — never feed raw logs; hard caps per tool result |
| GitHub rate limits during dev | SQLite response cache keyed by request hash |
| Scope creep | Anything not in Section 2 "In scope" gets a GitHub issue labeled `post-hackathon` and nothing else |

---

## 7. Post-Hackathon Startup Notes

- **Wedge:** teams already on Grafana/Prometheus + GitHub (huge install base, self-serve friendly).
- **Pricing intuition:** per-seat SRE tooling comps at $20–50/user/mo; or per-incident credits.
- **Expansion path:** Datadog/Sentry/PagerDuty connectors → Slack delivery → learned org memory ("this looks like INC-2041 from March").
- **Moat direction:** the evidence-linked investigation trace itself becomes training/eval data and an auditable compliance artifact — something incident-coordination tools don't have.

Good luck. Ship the loop, guard the scope, and make the live agent feed the star of the video.
