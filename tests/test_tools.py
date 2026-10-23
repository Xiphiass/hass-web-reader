"""Tests for the LLM tools."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from custom_components.extended_web_search import tools
from custom_components.extended_web_search.const import CONF_REQUEST_TIMEOUT
from custom_components.extended_web_search.tools import (
    OpenUrlTool,
    SearchWebTool,
    allocate_budget,
    select_candidates,
)

from .conftest import CONFIG, SEARXNG_URL

LLM_CONTEXT = llm.LLMContext(
    platform="test",
    context=None,
    language="en",
    assistant=None,
    device_id=None,
)


def _input(name: str, **args: Any) -> llm.ToolInput:
    return llm.ToolInput(tool_name=name, tool_args=args)


def _results(*urls: str) -> list[dict[str, str]]:
    return [{"url": u, "title": f"T {u}", "content": f"snippet {u}"} for u in urls]


def test_allocate_budget_redistributes() -> None:
    """Test short texts give their unused share to long ones."""
    assert allocate_budget([100, 5000, 5000], 3000) == [100, 1450, 1450]
    assert allocate_budget([10, 20], 1000) == [10, 20]
    assert allocate_budget([], 1000) == []


def test_select_candidates_filters() -> None:
    """Test duplicates, non-http and binary results are skipped."""
    results = [
        {"url": "https://a.com/x"},
        {"url": "https://a.com/x#frag"},
        {"url": "https://a.com/x/"},
        {"url": "ftp://b.com/"},
        {"url": "https://c.com/doc.PDF"},
        {"title": "no url"},
        {"url": "https://d.com/"},
    ]
    assert [c["url"] for c in select_candidates(results, 10)] == [
        "https://a.com/x",
        "https://d.com/",
    ]
    assert len(select_candidates(results, 1)) == 1


async def test_search_web_replaces_failed_pages(hass: HomeAssistant) -> None:
    """Test failed fetches are replaced by later candidates, in rank order."""
    pages = {
        "https://a.com/": {"error": "HTTP 403"},
        "https://b.com/": {"content": "B" * 900},
        "https://c.com/": {"content": "C" * 50},
        "https://d.com/": {"content": "D"},
    }

    async def fake_fetch(hass, session, url, max_length, timeout):
        return {"url": url, **pages[url]}

    tool = SearchWebTool(CONFIG, MagicMock())
    with (
        patch.object(
            tools,
            "async_search",
            AsyncMock(return_value=_results(*pages)),
        ) as mock_search,
        patch.object(tools, "fetch_page_content", side_effect=fake_fetch),
    ):
        result = await tool.async_call(
            hass, _input("search_web", query="q", time_range="week"), LLM_CONTEXT
        )

    assert mock_search.call_args.args[1] == SEARXNG_URL
    assert mock_search.call_args.kwargs["time_range"] == "week"
    assert [r["url"] for r in result["results"]] == ["https://b.com/", "https://c.com/"]
    # Short page leaves its unused budget to the long one
    assert result["results"][0]["content"] == "B" * 900
    assert "truncated" not in result["results"][0]


async def test_search_web_falls_back_to_snippets(hass: HomeAssistant) -> None:
    """Test snippets are used when too few pages can be fetched."""

    async def fake_fetch(hass, session, url, max_length, timeout):
        return {"url": url, "error": "HTTP 500"}

    tool = SearchWebTool(CONFIG, MagicMock())
    with (
        patch.object(
            tools, "async_search", AsyncMock(return_value=_results("https://a.com/"))
        ),
        patch.object(tools, "fetch_page_content", side_effect=fake_fetch),
    ):
        result = await tool.async_call(
            hass, _input("search_web", query="q"), LLM_CONTEXT
        )

    assert result["results"] == [
        {
            "title": "T https://a.com/",
            "url": "https://a.com/",
            "content": "snippet https://a.com/",
            "note": "Full page unavailable (HTTP 500); search snippet only",
        }
    ]


async def test_search_web_truncates_to_budget(hass: HomeAssistant) -> None:
    """Test combined content stays within the configured budget."""

    async def fake_fetch(hass, session, url, max_length, timeout):
        return {"url": url, "content": "x" * max_length}

    tool = SearchWebTool(CONFIG, MagicMock())
    with (
        patch.object(
            tools,
            "async_search",
            AsyncMock(return_value=_results("https://a.com/", "https://b.com/")),
        ),
        patch.object(tools, "fetch_page_content", side_effect=fake_fetch),
    ):
        result = await tool.async_call(
            hass, _input("search_web", query="q"), LLM_CONTEXT
        )

    assert sum(len(r["content"]) for r in result["results"]) == 1000
    assert all(r["truncated"] for r in result["results"])


async def test_search_web_overall_deadline(hass: HomeAssistant) -> None:
    """Test slow pages are abandoned at the deadline and fast ones returned."""

    async def fake_fetch(hass, session, url, max_length, timeout):
        if url == "https://slow.com/":
            await asyncio.sleep(10)
        return {"url": url, "content": "fast"}

    tool = SearchWebTool({**CONFIG, CONF_REQUEST_TIMEOUT: 0.2}, MagicMock())
    with (
        patch.object(
            tools,
            "async_search",
            AsyncMock(return_value=_results("https://slow.com/", "https://fast.com/")),
        ),
        patch.object(tools, "fetch_page_content", side_effect=fake_fetch),
    ):
        result = await tool.async_call(
            hass, _input("search_web", query="q"), LLM_CONTEXT
        )

    by_url = {r["url"]: r for r in result["results"]}
    assert by_url["https://fast.com/"]["content"] == "fast"
    assert "timed out" in by_url["https://slow.com/"]["note"]


async def test_search_web_stops_when_top_results_known(hass: HomeAssistant) -> None:
    """Test lower-ranked candidates are not awaited once enough pages are in."""

    async def fake_fetch(hass, session, url, max_length, timeout):
        if url == "https://c.com/":
            await asyncio.sleep(10)
        return {"url": url, "content": url}

    tool = SearchWebTool(CONFIG, MagicMock())
    with (
        patch.object(
            tools,
            "async_search",
            AsyncMock(
                return_value=_results(
                    "https://a.com/", "https://b.com/", "https://c.com/"
                )
            ),
        ),
        patch.object(tools, "fetch_page_content", side_effect=fake_fetch),
    ):
        result = await asyncio.wait_for(
            tool.async_call(hass, _input("search_web", query="q"), LLM_CONTEXT), 1
        )

    assert [r["url"] for r in result["results"]] == ["https://a.com/", "https://b.com/"]


async def test_search_web_search_error(hass: HomeAssistant) -> None:
    """Test SearXNG errors are reported to the LLM."""
    tool = SearchWebTool(CONFIG, MagicMock())
    with patch.object(
        tools, "async_search", AsyncMock(side_effect=tools.SearxngError("boom"))
    ):
        result = await tool.async_call(
            hass, _input("search_web", query="q"), LLM_CONTEXT
        )
    assert result == {"error": "Search failed: boom"}


async def test_open_url(hass: HomeAssistant) -> None:
    """Test open_url returns content and flags truncation."""

    async def fake_fetch(hass, session, url, max_length, timeout):
        return {"url": url + "final", "content": "y" * max_length}

    tool = OpenUrlTool(CONFIG, MagicMock())
    with patch.object(tools, "fetch_page_content", side_effect=fake_fetch):
        result = await tool.async_call(
            hass, _input("open_url", url="https://a.com/"), LLM_CONTEXT
        )
    assert result == {
        "url": "https://a.com/final",
        "content": "y" * 1000,
        "truncated": True,
    }


async def test_open_url_error(hass: HomeAssistant) -> None:
    """Test open_url passes errors through."""
    tool = OpenUrlTool(CONFIG, MagicMock())
    with patch.object(
        tools, "fetch_page_content", AsyncMock(return_value={"error": "HTTP 404"})
    ):
        result = await tool.async_call(
            hass, _input("open_url", url="https://a.com/"), LLM_CONTEXT
        )
    assert result == {"url": "https://a.com/", "error": "HTTP 404"}
