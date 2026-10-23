"""SearXNG client."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import aiohttp


class SearxngError(Exception):
    """SearXNG request failed."""


class SearxngJsonDisabledError(SearxngError):
    """SearXNG does not have the JSON output format enabled."""


def normalize_base_url(url: str) -> str | None:
    """Return the URL without trailing slash, or None if it is not http(s)."""
    url = url.strip().rstrip("/")
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return url


async def async_search(
    session: aiohttp.ClientSession,
    base_url: str,
    query: str,
    *,
    timeout: float,
    categories: str | None = None,
    time_range: str | None = None,
) -> list[dict[str, Any]]:
    """Query SearXNG and return the raw result list."""
    params = {"q": query, "format": "json"}
    if categories:
        params["categories"] = categories
    if time_range:
        params["time_range"] = time_range

    async with session.get(
        f"{base_url}/search",
        params=params,
        headers={"Accept": "application/json"},
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        if resp.status == 403:
            raise SearxngJsonDisabledError(
                "SearXNG refused the JSON request (HTTP 403); "
                "enable the json format in settings.yml"
            )
        if resp.status != 200:
            raise SearxngError(f"SearXNG returned HTTP {resp.status}")
        try:
            data = await resp.json(content_type=None)
        except ValueError as err:
            raise SearxngJsonDisabledError(
                "SearXNG did not return JSON; enable the json format in settings.yml"
            ) from err

    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise SearxngError("Unexpected response from SearXNG")
    return results
