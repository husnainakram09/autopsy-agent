from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx


class LokiClient:
    """Async Loki query client returning compact log entries."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
    ) -> None:
        self.base_url = (base_url or os.getenv("LOKI_URL", "http://localhost:3100")).rstrip("/")
        self._client = client
        self._owns_client = client is None
        self.max_retries = max(0, max_retries)
        self.backoff_factor = backoff_factor

    async def __aenter__(self) -> "LokiClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def query_logs(
        self,
        logql: str,
        start: str | datetime,
        end: str | datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            "/loki/api/v1/query_range",
            params={
                "query": logql,
                "start": self._timestamp_ns(start),
                "end": self._timestamp_ns(end),
                "limit": str(max(1, limit)),
                "direction": "backward",
            },
        )
        if payload.get("status") != "success":
            raise RuntimeError(payload.get("error", "Loki query failed"))

        entries: list[dict[str, Any]] = []
        for stream in payload.get("data", {}).get("result", []):
            labels = stream.get("stream", {})
            for timestamp, line in stream.get("values", []):
                entry = {"timestamp": timestamp, "line": line}
                if labels:
                    entry["labels"] = labels
                entries.append(entry)
        return entries[: max(1, limit)]

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
        raise RuntimeError("Loki retry loop ended unexpectedly")

    @staticmethod
    def _timestamp_ns(value: str | datetime) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return str(int(value.timestamp() * 1_000_000_000))
        if value.isdigit():
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return str(int(parsed.timestamp() * 1_000_000_000))


_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", re.IGNORECASE)
_HEX_ID_RE = re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{8,}\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")
_SPACE_RE = re.compile(r"\s+")
_ERROR_RE = re.compile(r"\b(error|exception|failed|failure|timeout|timed out|traceback)\b", re.IGNORECASE)


def _line_text(entry: Any) -> str:
    line = entry.get("line", "") if isinstance(entry, dict) else str(entry)
    if not isinstance(line, str):
        line = str(line)
    try:
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            for key in ("message", "error", "exception", "detail"):
                if parsed.get(key):
                    return str(parsed[key])
    except (TypeError, json.JSONDecodeError):
        pass
    return line


def normalize_error_template(message: str) -> str:
    """Replace IDs and numbers so equivalent errors share one cluster."""
    normalized = _UUID_RE.sub("<id>", message)
    normalized = _HEX_ID_RE.sub("<id>", normalized)
    normalized = _NUMBER_RE.sub("<n>", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def cluster_errors(entries: Iterable[dict[str, Any] | str], top: int = 10) -> list[dict[str, Any]]:
    """Group error-like log lines and return only the top clusters and 2 samples."""
    clusters: dict[str, dict[str, Any]] = {}
    for entry in entries:
        line = _line_text(entry)
        if not _ERROR_RE.search(line):
            continue
        template = normalize_error_template(line)
        cluster = clusters.setdefault(template, {"template": template, "count": 0, "samples": []})
        cluster["count"] += 1
        if len(cluster["samples"]) < 2:
            cluster["samples"].append(line)
    return sorted(clusters.values(), key=lambda cluster: (-cluster["count"], cluster["template"]))[: max(1, top)]


async def query_logs(
    logql: str,
    start: str | datetime,
    end: str | datetime,
    limit: int,
    **client_options: Any,
) -> list[dict[str, Any]]:
    """Convenience wrapper using the configured Loki URL."""
    async with LokiClient(**client_options) as client:
        return await client.query_logs(logql, start, end, limit)

