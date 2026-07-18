from pathlib import Path

import httpx
import pytest
import respx

from app.tools.logs import LokiClient, cluster_errors
from app.tools.metrics import PrometheusClient


@pytest.mark.asyncio
@respx.mock
async def test_prometheus_query_range_downsamples_and_detects_spike(tmp_path: Path):
    route = respx.get("http://prometheus.test/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "metric": {"job": "orders"},
                            "values": [[index, str(100 if index == 149 else 1)] for index in range(150)],
                        }
                    ]
                },
            },
        )
    )
    async with PrometheusClient(base_url="http://prometheus.test") as client:
        result = await client.query_range("rate(http_requests_total[5m])", "1", "2", 15)

    series = result["series"][0]
    assert len(series["points"]) == 100
    assert series["summary"]["min"] == 1
    assert series["summary"]["max"] == 100
    assert series["summary"]["spikes"][0]["timestamp"] == 149
    assert route.calls[0].request.url.params["query"] == "rate(http_requests_total[5m])"


@pytest.mark.asyncio
@respx.mock
async def test_loki_query_logs_flattens_streams_and_limits_entries():
    respx.get("http://loki.test/loki/api/v1/query_range").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "result": [
                        {
                            "stream": {"app": "orders"},
                            "values": [["2", "second"], ["1", "first"]],
                        }
                    ]
                },
            },
        )
    )
    async with LokiClient(base_url="http://loki.test") as client:
        entries = await client.query_logs("{app=\"orders\"}", "1", "2", 1)

    assert entries == [{"timestamp": "2", "line": "second", "labels": {"app": "orders"}}]


def test_cluster_errors_normalizes_ids_and_keeps_two_samples():
    entries = [
        {"line": '{"level":"ERROR","message":"timeout fetching order 123"}'},
        {"line": '{"level":"ERROR","message":"timeout fetching order 456"}'},
        {"line": "database connection failed for request 999"},
    ]

    clusters = cluster_errors(entries)

    assert clusters[0]["template"] == "timeout fetching order <n>"
    assert clusters[0]["count"] == 2
    assert len(clusters[0]["samples"]) == 2
