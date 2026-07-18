from __future__ import annotations

import asyncio
import math
import os
from datetime import datetime, timezone
from typing import Any

import httpx


class PrometheusClient:
    """Async Prometheus range-query client that returns LLM-sized summaries."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self.base_url = (base_url or os.getenv("PROMETHEUS_URL", "http://localhost:9090")).rstrip("/")
        self._client = client
        self._owns_client = client is None
        self.max_retries = max(0, max_retries)
        self.backoff_factor = backoff_factor

    async def __aenter__(self) -> "PrometheusClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def query_range(
        self,
        promql: str,
        start: str | datetime,
        end: str | datetime,
        step: str | int | float,
    ) -> dict[str, Any]:
        """Query Prometheus and summarize each returned time series.

        Each series is reduced to at most 100 evenly spaced points. Statistics
        and spike detection are calculated from all finite raw values.
        """
        payload = await self._get(
            "/api/v1/query_range",
            params={
                "query": promql,
                "start": self._timestamp_param(start),
                "end": self._timestamp_param(end),
                "step": str(step),
            },
        )
        if payload.get("status") != "success":
            raise RuntimeError(payload.get("error", "Prometheus query failed"))

        result = payload.get("data", {}).get("result", [])
        series = []
        for item in result:
            raw_points = []
            for timestamp, raw_value in item.get("values", []):
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(value):
                    raw_points.append({"timestamp": timestamp, "value": value})
            series.append(
                {
                    "labels": item.get("metric", {}),
                    "points": self._downsample(raw_points, 100),
                    "summary": self._summary(raw_points),
                }
            )
        return {"series": series, "series_count": len(series)}

    async def _get(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        url = f"{self.base_url}/{path.lstrip('/')}"
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt >= self.max_retries:
                        response.raise_for_status()
                    await asyncio.sleep(self.backoff_factor * (2**attempt))
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.RequestError, httpx.TimeoutException):
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.backoff_factor * (2**attempt))
        raise RuntimeError("Prometheus retry loop ended unexpectedly")

    @staticmethod
    def _timestamp_param(value: str | datetime) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value

    @staticmethod
    def _downsample(points: list[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
        if len(points) <= maximum:
            return points
        indexes = [round(index * (len(points) - 1) / (maximum - 1)) for index in range(maximum)]
        return [points[index] for index in indexes]

    @staticmethod
    def _summary(points: list[dict[str, Any]]) -> dict[str, Any]:
        values = [point["value"] for point in points]
        if not values:
            return {"count": 0, "min": None, "max": None, "mean": None, "spikes": []}
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        standard_deviation = math.sqrt(variance)
        spikes = []
        if standard_deviation:
            for point in points:
                z_score = (point["value"] - mean) / standard_deviation
                if z_score > 3:
                    spikes.append({"timestamp": point["timestamp"], "value": point["value"], "z": round(z_score, 2)})
        spikes.sort(key=lambda spike: spike["z"], reverse=True)
        return {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "mean": round(mean, 6),
            "spikes": spikes[:20],
        }


async def query_range(
    promql: str,
    start: str | datetime,
    end: str | datetime,
    step: str | int | float,
    **client_options: Any,
) -> dict[str, Any]:
    """Convenience wrapper using the configured Prometheus URL."""
    async with PrometheusClient(**client_options) as client:
        return await client.query_range(promql, start, end, step)

