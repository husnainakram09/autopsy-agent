# Autopsy Agent

Monorepo for the Autopsy Agent application.

## Stack

- `backend`: FastAPI, Python 3.12, SQLModel, SQLite, and `uv`
- `frontend`: React 18, Vite, TypeScript, Tailwind CSS, and shadcn/ui

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 18+
- npm
- Git
- Docker Desktop with Docker Compose
- Optional: Git Bash or WSL if you want to use `make` or the incident shell scripts

## Windows setup

Open PowerShell in the repository root (`D:\autopsy-agent`) and install dependencies:

```powershell
Set-Location D:\autopsy-agent\backend
uv sync

Set-Location ..\frontend
npm install --legacy-peer-deps

Set-Location ..
```

Run the backend tests from PowerShell:

```powershell
uv run --project .\backend pytest
```

Start development servers in two PowerShell windows. In the first window:

```powershell
Set-Location D:\autopsy-agent
uv run --project .\backend uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In the second window:

```powershell
Set-Location D:\autopsy-agent
npm --prefix .\frontend run dev
```

The API is available at `http://localhost:8000` and the Vite app at `http://localhost:5173`.

The SQLite database is created at `backend/data/app.db` when the backend starts.

### Optional Git Bash / WSL shortcut

From Git Bash:

```bash
cd /d/autopsy-agent
make dev
```

From WSL:

```bash
cd /mnt/d/autopsy-agent
make dev
```

## API

- `GET /health` — returns `{ "status": "ok" }`
- `GET /runs/{id}/stream` — streams investigation events as SSE; reconnects replay buffered events and honor `Last-Event-ID`.

## Observability demo stack

The `demo-stack` directory is a standalone Docker Compose demo of an instrumented orders service:

- FastAPI orders API backed by Postgres at `http://localhost:8001`
- Prometheus at `http://localhost:9090`
- Grafana at `http://localhost:3000` (login: `admin` / `admin`)
- Loki at `http://localhost:3100`
- Promtail collecting Docker JSON logs and forwarding them to Loki
- Alertmanager forwarding firing alerts to the Autopsy Agent webhook
- A continuously running `loadgen` container that exercises list, create, checkout, and not-found traffic

Start everything from PowerShell at the repository root:

```powershell
docker compose -f .\demo-stack\docker-compose.yml up --build
```

Open Grafana and select the pre-provisioned **Orders Service Observability** dashboard. It includes request rate, error rate, and p95 latency panels backed by Prometheus. Logs are available through the provisioned Loki data source using the Explore view.

Prometheus evaluates `OrdersHighErrorRate` when the orders service error rate exceeds 5% for two minutes. Alertmanager forwards the firing alert to `POST /webhooks/alertmanager`, which creates an incident, creates a run, and starts the investigation agent in the background. Run `make dev` first so the webhook is available at `http://host.docker.internal:8000`, then start the demo stack. The response includes the incident and run IDs, and the UI can follow the run over SSE.

> Demo line: **“no human even clicked Investigate.”**

Stop the stack with `Ctrl+C`, or run:

```powershell
docker compose -f .\demo-stack\docker-compose.yml down
```

Add `-v` to remove the Postgres, Prometheus, Loki, and Grafana volumes:

```powershell
docker compose -f .\demo-stack\docker-compose.yml down -v
```

### Incident drill: N+1 query and pool exhaustion

The repository includes an intentionally faulty branch, `incident/n-plus-one`. The branch adds an N+1 query pattern to `GET /orders` and reduces the orders database pool to three connections so the existing load generator can produce latency spikes and pool timeouts.

From Git Bash with Docker Desktop running:

```bash
./scripts/trigger_incident.sh
```

The scripts are Bash scripts and are not directly executable from PowerShell. In WSL, use the same commands from `/mnt/d/autopsy-agent`.

That checks out `main`, merges the incident branch, and rebuilds the orders and loadgen containers. Use the provisioned Grafana dashboard and container logs to observe the impact. Resolve and redeploy with:

```bash
./scripts/resolve_incident.sh
```

The resolve script reverts the incident merge commit and rebuilds the affected containers. These scripts expect a clean working tree because they switch to `main` before merging or reverting.

### Incident drill: downstream timeout

The `incident/bad-timeout` branch adds an inventory dependency with normal 50–180ms latency variance, then intentionally constrains the orders client timeout to 100ms. This produces intermittent `502` responses without the database query amplification and pool pressure characteristic of `incident/n-plus-one`.

```bash
git checkout incident/bad-timeout
docker compose -f demo-stack/docker-compose.yml up --build
```

The agent should identify the timeout by correlating `502` responses and downstream latency with the `timeout=0.1` code diff. It should not label the incident N+1: that scenario requires query growth/pool pressure evidence and an item-by-item database access diff.

## Investigation graceful degradation

- Tool timeouts are persisted as evidence and emitted as `tool_timeout` feed events. The agent receives an explicit instruction to continue with partial evidence and use another signal.
- Each run has a five-minute watchdog. If it expires, the run is marked timed out and a partial, evidence-linked report is salvaged and emitted to the feed.
- When the conversation estimate exceeds the configured token threshold, prior context is compacted into a summary while recent tool results and artifact IDs are retained.
- The frontend has a global render error boundary with a retry action. Safe idempotent GET requests retry transient network and 5xx failures with backoff; run-start POSTs are not automatically replayed.
