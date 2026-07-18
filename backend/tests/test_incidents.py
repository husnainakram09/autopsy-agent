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
