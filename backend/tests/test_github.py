from pathlib import Path

import httpx
import pytest
import respx

from app.tools.github import GitHubClient


@pytest.mark.asyncio
@respx.mock
async def test_list_commits_includes_changed_files_and_uses_cache(tmp_path: Path):
    base = "https://api.github.test"
    commits = respx.get(f"{base}/repos/acme/shop/commits").mock(
        return_value=httpx.Response(200, json=[{"sha": "abc123"}])
    )
    detail = respx.get(f"{base}/repos/acme/shop/commits/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "sha": "abc123",
                "author": {"login": "octocat"},
                "commit": {
                    "message": "Ship checkout",
                    "author": {"name": "Octo Cat", "date": "2026-07-18T00:00:00Z"},
                },
                "files": [{"filename": "app/checkout.py"}],
            },
        )
    )

    async with GitHubClient(
        token="secret", base_url=base, cache_path=tmp_path / "cache.db"
    ) as client:
        result = await client.list_commits("acme/shop", "2026-07-01T00:00:00Z", "2026-07-18T00:00:00Z")
        cached_result = await client.list_commits("acme/shop", "2026-07-01T00:00:00Z", "2026-07-18T00:00:00Z")

    assert result == [{
        "sha": "abc123",
        "author": "octocat",
        "message": "Ship checkout",
        "timestamp": "2026-07-18T00:00:00Z",
        "changed_files": ["app/checkout.py"],
    }]
    assert cached_result == result
    assert commits.call_count == 1
    assert detail.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_commit_diff_is_truncated(tmp_path: Path):
    base = "https://api.github.test"
    diff = "diff --git a/file b/file\n" + ("+change\n" * 2000)
    route = respx.get(f"{base}/repos/acme/shop/commits/abc123").mock(
        return_value=httpx.Response(200, text=diff)
    )

    async with GitHubClient(base_url=base, cache_path=tmp_path / "cache.db") as client:
        result = await client.get_commit_diff("acme/shop", "abc123")

    assert len(result) > 8000
    assert result.startswith(diff[:8000])
    assert "[diff truncated to 8000 characters]" in result
    assert route.calls[0].request.headers["accept"] == "application/vnd.github.diff"


@pytest.mark.asyncio
@respx.mock
async def test_retries_server_error_and_filters_deployments(tmp_path: Path):
    base = "https://api.github.test"
    route = respx.get(f"{base}/repos/acme/shop/deployments").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json=[
                    {"id": 1, "created_at": "2026-07-17T00:00:00Z"},
                    {"id": 2, "created_at": "2026-07-18T00:00:00Z"},
                ],
            ),
        ]
    )

    async with GitHubClient(
        base_url=base, cache_path=tmp_path / "cache.db", backoff_factor=0
    ) as client:
        result = await client.list_deployments("acme/shop", "2026-07-18T00:00:00Z")

    assert result == [{"id": 2, "created_at": "2026-07-18T00:00:00Z"}]
    assert route.call_count == 2
