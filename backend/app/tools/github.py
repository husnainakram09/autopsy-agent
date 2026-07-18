from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


class GitHubClient:
    """Small async GitHub API client with retries and a persistent response cache."""

    def __init__(
        self,
        token: str | None = None,
        *,
        base_url: str | None = None,
        cache_path: str | Path | None = None,
        cache_ttl_seconds: int = 3600,
        max_retries: int = 3,
        backoff_factor: float = 0.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token if token is not None else os.getenv("GITHUB_TOKEN")
        self.base_url = (base_url or os.getenv("GITHUB_API_URL", "https://api.github.com")).rstrip("/")
        self.cache_path = Path(
            cache_path
            or os.getenv(
                "GITHUB_CACHE_DB",
                Path(__file__).resolve().parents[2] / "data" / "github_cache.db",
            )
        )
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_retries = max(0, max_retries)
        self.backoff_factor = backoff_factor
        self._client = client
        self._owns_client = client is None
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_cache()

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _initialize_cache(self) -> None:
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS github_request_cache (
                    request_hash TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

    @staticmethod
    def _request_hash(method: str, url: str, params: dict[str, Any] | None) -> str:
        request = json.dumps(
            {"method": method.upper(), "url": url, "params": params or {}},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(request.encode("utf-8")).hexdigest()

    def _read_cache(self, request_hash: str) -> Any | None:
        with sqlite3.connect(self.cache_path) as connection:
            row = connection.execute(
                "SELECT response_json, created_at FROM github_request_cache WHERE request_hash = ?",
                (request_hash,),
            ).fetchone()
        if row is None:
            return None
        if self.cache_ttl_seconds >= 0 and datetime.now(timezone.utc).timestamp() - row[1] > self.cache_ttl_seconds:
            return None
        return json.loads(row[0])

    def _write_cache(self, request_hash: str, response: Any) -> None:
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                """
                INSERT INTO github_request_cache(request_hash, response_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(request_hash) DO UPDATE SET
                    response_json = excluded.response_json,
                    created_at = excluded.created_at
                """,
                (request_hash, json.dumps(response), datetime.now(timezone.utc).timestamp()),
            )

    async def _request_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        request_hash = self._request_hash("GET", url, params)
        cached = await asyncio.to_thread(self._read_cache, request_hash)
        if cached is not None:
            return cached

        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                    **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                },
                timeout=20.0,
            )

        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt >= self.max_retries:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else self.backoff_factor * (2**attempt)
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                payload = response.json()
                await asyncio.to_thread(self._write_cache, request_hash, payload)
                return payload
            except (httpx.RequestError, httpx.TimeoutException):
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.backoff_factor * (2**attempt))
        raise RuntimeError("GitHub request retry loop ended unexpectedly")

    async def list_commits(
        self, repo: str, since: str | datetime | None = None, until: str | datetime | None = None
    ) -> list[dict[str, Any]]:
        params = self._date_params(since, until)
        summaries = await self._request_json(f"/repos/{repo}/commits", params or None)

        async def commit_details(summary: dict[str, Any]) -> dict[str, Any]:
            sha = summary["sha"]
            detail = await self._request_json(f"/repos/{repo}/commits/{sha}")
            commit = detail.get("commit", {})
            author = detail.get("author") or {}
            commit_author = commit.get("author") or {}
            return {
                "sha": sha,
                "author": author.get("login") or commit_author.get("name"),
                "message": commit.get("message", ""),
                "timestamp": commit_author.get("date"),
                "changed_files": [file.get("filename") for file in detail.get("files", [])],
            }

        return await asyncio.gather(*(commit_details(summary) for summary in summaries))

    async def get_commit_diff(self, repo: str, sha: str) -> str:
        url_path = f"/repos/{repo}/commits/{sha}"
        request_hash = self._request_hash("GET", f"{self.base_url}/{url_path.lstrip('/')}", {"diff": True})
        cached = await asyncio.to_thread(self._read_cache, request_hash)
        if cached is None:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    headers={
                        "Accept": "application/vnd.github.diff",
                        "X-GitHub-Api-Version": "2022-11-28",
                        **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                    },
                    timeout=20.0,
                )
            response = await self._request_with_retry(
                f"{self.base_url}/{url_path.lstrip('/')}",
                headers={"Accept": "application/vnd.github.diff"},
            )
            cached = response.text
            await asyncio.to_thread(self._write_cache, request_hash, cached)
        diff = str(cached)
        if len(diff) > 8000:
            return diff[:8000] + "\n\n[diff truncated to 8000 characters]"
        return diff

    async def _request_with_retry(self, url: str, headers: dict[str, str]) -> httpx.Response:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=20.0)
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(url, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt >= self.max_retries:
                        response.raise_for_status()
                    await asyncio.sleep(self.backoff_factor * (2**attempt))
                    continue
                response.raise_for_status()
                return response
            except (httpx.RequestError, httpx.TimeoutException):
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(self.backoff_factor * (2**attempt))
        raise RuntimeError("GitHub request retry loop ended unexpectedly")

    async def list_deployments(self, repo: str, since: str | datetime | None = None) -> list[dict[str, Any]]:
        deployments = await self._request_json(f"/repos/{repo}/deployments")
        if since is None:
            return deployments
        since_value = self._to_iso(since)
        return [
            deployment
            for deployment in deployments
            if (deployment.get("created_at") or deployment.get("updated_at") or "") >= since_value
        ]

    @staticmethod
    def _to_iso(value: str | datetime) -> str:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return value

    @classmethod
    def _date_params(cls, since: str | datetime | None, until: str | datetime | None) -> dict[str, str]:
        params: dict[str, str] = {}
        if since is not None:
            params["since"] = cls._to_iso(since)
        if until is not None:
            params["until"] = cls._to_iso(until)
        return params

