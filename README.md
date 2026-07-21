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
- GNU Make (or a compatible Make implementation)

## Getting started

Install dependencies:

```bash
cd backend && uv sync
cd ../frontend && npm install
```

Run the backend tests:

```bash
cd backend && uv run pytest
```

Run both development servers from the repository root:

```bash
make dev
```

The API is available at `http://localhost:8000` and the Vite app at `http://localhost:5173`.

The SQLite database is created at `backend/data/app.db` when the backend starts.

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
- A continuously running `loadgen` container that exercises list, create, checkout, and not-found traffic

Start everything from the repository root:

```bash
cd demo-stack
docker compose up --build
```

Open Grafana and select the pre-provisioned **Orders Service Observability** dashboard. It includes request rate, error rate, and p95 latency panels backed by Prometheus. Logs are available through the provisioned Loki data source using the Explore view.

Stop the stack with `Ctrl+C`, or run `docker compose down`. Add `-v` to remove the Postgres, Prometheus, Loki, and Grafana volumes as well.

### Incident drill: N+1 query and pool exhaustion

The repository includes an intentionally faulty branch, `incident/n-plus-one`. The branch adds an N+1 query pattern to `GET /orders` and reduces the orders database pool to three connections so the existing load generator can produce latency spikes and pool timeouts.

From a Git Bash shell with Docker running:

```bash
./scripts/trigger_incident.sh
```

That checks out `main`, merges the incident branch, and rebuilds the orders and loadgen containers. Use the provisioned Grafana dashboard and container logs to observe the impact. Resolve and redeploy with:

```bash
./scripts/resolve_incident.sh
```

The resolve script reverts the incident merge commit and rebuilds the affected containers. These scripts expect a clean working tree because they switch to `main` before merging or reverting.
