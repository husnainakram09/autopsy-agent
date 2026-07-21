from fastapi.testclient import TestClient

from app.db import create_db_and_tables
from app.main import app


def test_incident_run_and_artifact_endpoints():
    create_db_and_tables()
    with TestClient(app) as client:
        incident_response = client.post(
            "/incidents",
            json={"title": "Checkout latency", "status": "open"},
        )
        assert incident_response.status_code == 201
        incident_id = incident_response.json()["id"]

        run_response = client.post(f"/incidents/{incident_id}/runs", json={"status": "running"})
        assert run_response.status_code == 201
        run_id = run_response.json()["id"]

        artifact_response = client.post(
            f"/runs/{run_id}/artifacts",
            json={
                "tool_name": "prometheus.query_range",
                "input_json": {"query": "rate(http_requests_total[5m])"},
                "output_json": {"series": []},
                "summary": "No significant spike",
            },
        )
        assert artifact_response.status_code == 201

        listed = client.get(f"/runs/{run_id}/artifacts")
        assert listed.status_code == 200
        assert listed.json()[0]["tool_name"] == "prometheus.query_range"

        incident = client.get(f"/incidents/{incident_id}")
        assert incident.status_code == 200
        assert incident.json()["incident"]["title"] == "Checkout latency"
        assert incident.json()["runs"][0]["id"] == run_id


def test_alertmanager_webhook_creates_incident_and_starts_run(monkeypatch):
    started: list[int] = []

    async def fake_start(run_id: int) -> None:
        started.append(run_id)

    monkeypatch.setattr("app.main._run_investigation", fake_start)
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/alertmanager",
            json={
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "OrdersHighErrorRate", "service": "orders"},
                        "annotations": {"summary": "Orders error rate above 5%"},
                        "startsAt": "2026-07-19T10:00:00Z",
                    }
                ],
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "accepted"
        assert body["incident_id"]
        assert body["run_id"] in started


def test_alertmanager_webhook_ignores_resolved_alerts():
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/alertmanager",
            json={"status": "resolved", "alerts": [{"status": "resolved"}]},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "ignored"
