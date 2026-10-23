"""LLM tools for Extended Web Search."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urldefrag, urlparse

import aiohttp
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.json import JsonObjectType

from .const import (
    CANDIDATE_FACTOR,
    CATEGORIES,
    CONF_MAX_CONTENT_LENGTH,
    CONF_NUM_RESULTS,
    CONF_REQUEST_TIMEOUT,
    CONF_SEARXNG_URL,
    TIME_RANGES,
)
from .searxng import SearxngError, async_search
from .web_content import fetch_page_content

_LOGGER = logging.getLogger(__name__)

# Result URLs that are never HTML and would only waste a fetch
SKIP_EXTENSIONS = (
    ".pdf", ".zip", ".gz", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".mkv", ".jpg", ".jpeg", ".png", ".gif",
)  # fmt: skip


def select_candidates(
    results: list[dict[str, Any]], limit: int
) -> list[dict[str, str]]:
    """Pick fetchable, de-duplicated results in rank order."""
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in results:
        url = item.get("url")
        if not isinstance(url, str):
            continue
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.path.lower().endswith(SKIP_EXTENSIONS):
            continue
        key = urldefrag(url).url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "title": str(item.get("title") or ""),
                "url": url,
                "snippet": str(item.get("content") or ""),
            }
        )
        if len(candidates) >= limit:
            break
    return candidates


def allocate_budget(lengths: list[int], total: int) -> list[int]:
    """Split a character budget so short texts give their unused share to long ones."""
    allocation = [0] * len(lengths)
    remaining = total
    order = sorted(range(len(lengths)), key=lambda i: lengths[i])
    for position, index in enumerate(order):
        share = remaining // (len(lengths) - position)
        allocation[index] = min(lengths[index], share)
        remaining -= allocation[index]
    return allocation


def _succeeded(task: asyncio.Task[dict[str, Any]]) -> bool:
    """Return True if a finished fetch task produced content."""
    return (
        not task.cancelled() and task.exception() is None and "content" in task.result()
    )


def _have_enough(tasks: list[asyncio.Task[dict[str, Any]]], wanted: int) -> bool:
    """Return True once the top `wanted` successful fetches (in rank order) are known."""
    found = 0
    for task in tasks:
        if not task.done():
            return False
        if _succeeded(task):
            found += 1
            if found >= wanted:
                return True
    return True


class SearchWebTool(llm.Tool):
    """Search the web via SearXNG and fetch full page content from results."""

    name = "search_web"
    description = (
        "Searches the web and returns the extracted text of the top result "
        "pages, not just snippets. Use it for current events or facts you "
        "do not know."
    )
    parameters = vol.Schema(
        {
            vol.Required("query", description="The search query"): str,
            vol.Optional(
                "time_range",
                description="Only return results from this recent period",
            ): vol.In(TIME_RANGES),
            vol.Optional(
                "category",
                description="Search category, e.g. news for current events",
            ): vol.In(CATEGORIES),
        }
    )

    def __init__(
        self, config: dict[str, Any], fetch_session: aiohttp.ClientSession
    ) -> None:
        """Initialize the tool."""
        super().__init__()
        self.config = config
        self.fetch_session = fetch_session

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Perform web search and fetch page content."""
        args = tool_input.tool_args
        query = args["query"]
        _LOGGER.debug("Extended web search for: %s", query)

        num_results = int(self.config[CONF_NUM_RESULTS])
        max_content_length = int(self.config[CONF_MAX_CONTENT_LENGTH])
        timeout = float(self.config[CONF_REQUEST_TIMEOUT])
        deadline = hass.loop.time() + timeout

        try:
            raw_results = await async_search(
                async_get_clientsession(hass),
                self.config[CONF_SEARXNG_URL],
                query,
                timeout=timeout,
                categories=args.get("category"),
                time_range=args.get("time_range"),
            )
        except TimeoutError:
            return {"error": "Search timed out"}
        except (aiohttp.ClientError, SearxngError) as err:
            _LOGGER.warning("SearXNG search failed: %s", err)
            return {"error": f"Search failed: {err!s}"}

        candidates = select_candidates(raw_results, num_results * CANDIDATE_FACTOR)
        if not candidates:
            return {"query": query, "results": [], "note": "No search results found"}

        remaining = max(deadline - hass.loop.time(), 0.1)
        pages = await self._fetch_pages(
            hass, candidates, num_results, max_content_length, remaining
        )

        # Top successful fetches, topped up with snippets of failed ones
        fetched = [i for i, page in enumerate(pages) if page and "content" in page]
        failed = [
            i for i, page in enumerate(pages) if not page or "content" not in page
        ]
        selected = fetched[:num_results]
        selected = sorted(selected + failed[: num_results - len(selected)])

        chosen: list[dict[str, Any]] = []
        for index in selected:
            candidate, page = candidates[index], pages[index]
            entry: dict[str, Any] = {
                "title": candidate["title"],
                "url": candidate["url"],
            }
            if page and "content" in page:
                entry["content"] = page["content"]
            else:
                entry["content"] = candidate["snippet"]
                entry["note"] = (
                    f"Full page unavailable ({page['error'] if page else 'timed out'}); "
                    "search snippet only"
                )
            chosen.append(entry)

        budgets = allocate_budget(
            [len(e["content"]) for e in chosen], max_content_length
        )
        for entry, budget in zip(chosen, budgets, strict=True):
            if len(entry["content"]) > budget:
                entry["content"] = entry["content"][:budget]
                entry["truncated"] = True

        return {"query": query, "results": chosen}

    async def _fetch_pages(
        self,
        hass: HomeAssistant,
        candidates: list[dict[str, str]],
        wanted: int,
        max_length: int,
        timeout: float,
    ) -> list[dict[str, Any] | None]:
        """Fetch candidates in parallel until the top `wanted` are known or time is up.

        Returns one result per candidate; None if it did not finish in time.
        """
        tasks = [
            asyncio.create_task(
                fetch_page_content(
                    hass, self.fetch_session, c["url"], max_length, timeout
                )
            )
            for c in candidates
        ]
        pending: set[asyncio.Task[dict[str, Any]]] = set(tasks)
        try:
            async with asyncio.timeout(timeout):
                while pending and not _have_enough(tasks, wanted):
                    _, pending = await asyncio.wait(
                        pending, return_when=asyncio.FIRST_COMPLETED
                    )
        except TimeoutError:
            pass
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        results: list[dict[str, Any] | None] = []
        for task in tasks:
            if not task.done() or task.cancelled():
                results.append(None)
            elif (err := task.exception()) is not None:
                results.append({"error": f"Failed to fetch: {err!s}"})
            else:
                results.append(task.result())
        return results


class OpenUrlTool(llm.Tool):
    """Fetch and extract content from a specific URL."""

    name = "open_url"
    description = (
        "Fetches a public web page and returns its extracted text. Use it to "
        "read a result from search_web in more detail or a page the user "
        "named. Only public http/https HTML pages are supported."
    )
    parameters = vol.Schema(
        {
            vol.Required("url", description="The URL of the web page to fetch"): str,
        }
    )

    def __init__(
        self, config: dict[str, Any], fetch_session: aiohttp.ClientSession
    ) -> None:
        """Initialize the tool."""
        super().__init__()
        self.config = config
        self.fetch_session = fetch_session

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Fetch URL content."""
        url = tool_input.tool_args["url"]
        _LOGGER.debug("Fetching URL: %s", url)

        max_content_length = int(self.config[CONF_MAX_CONTENT_LENGTH])
        timeout = float(self.config[CONF_REQUEST_TIMEOUT])

        # Fetch one extra character to tell whether the page was cut off
        result = await fetch_page_content(
            hass, self.fetch_session, url, max_content_length + 1, timeout
        )
        if "error" in result:
            return {"url": url, "error": result["error"]}

        response: dict[str, Any] = {"url": result["url"], "content": result["content"]}
        if len(result["content"]) > max_content_length:
            response["content"] = result["content"][:max_content_length]
            response["truncated"] = True
        return response
