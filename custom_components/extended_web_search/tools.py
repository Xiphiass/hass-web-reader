"""LLM tools for Extended Web Search."""

from __future__ import annotations

import asyncio
import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util.json import JsonObjectType

from .const import (
    CONF_MAX_CONTENT_LENGTH,
    CONF_NUM_RESULTS,
    CONF_REQUEST_TIMEOUT,
    CONF_SEARXNG_URL,
    DEFAULT_MAX_CONTENT_LENGTH,
    DEFAULT_NUM_RESULTS,
    DEFAULT_REQUEST_TIMEOUT,
)
from .web_content import fetch_page_content

_LOGGER = logging.getLogger(__name__)


class SearchWebTool(llm.Tool):
    """Search the web via SearXNG and fetch full page content from results."""

    name = "search_web"
    description = (
        "Performs a web search using the given query and retrieves the actual "
        "content from the top result pages. Use this to look up current information, "
        "answer factual questions, research topics, or verify claims. "
        "Returns the full extracted text content from each result page, "
        "not just snippets."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "query", description="The search query to look up"
            ): str,
        }
    )

    def __init__(self, config: dict, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        super().__init__()
        self.config = config
        self.hass = hass

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Perform web search and fetch page content."""
        query = tool_input.tool_args["query"]
        _LOGGER.info("Extended web search for: %s", query)

        searxng_url = self.config.get(CONF_SEARXNG_URL, "")
        num_results = int(self.config.get(CONF_NUM_RESULTS, DEFAULT_NUM_RESULTS))
        max_content_length = int(
            self.config.get(CONF_MAX_CONTENT_LENGTH, DEFAULT_MAX_CONTENT_LENGTH)
        )
        timeout = int(self.config.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT))

        if not searxng_url:
            return {"error": "SearXNG server URL not configured"}

        # Step 1: Query SearXNG
        try:
            search_results = await self._search_searxng(
                searxng_url, query, num_results, timeout
            )
        except Exception as e:
            _LOGGER.exception("SearXNG search failed")
            return {"error": f"Search failed: {e!s}"}

        if not search_results:
            return {"results": "No search results found"}

        # Step 2: Fetch content from result URLs in parallel
        # Distribute max content length across results
        per_page_length = max_content_length // len(search_results)

        fetch_tasks = [
            fetch_page_content(hass, result["url"], per_page_length, timeout)
            for result in search_results
        ]
        fetched_pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        # Step 3: Combine results
        combined_results = []
        for i, result in enumerate(search_results):
            entry = {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
            }

            page_data = fetched_pages[i]
            if isinstance(page_data, Exception):
                entry["content"] = result.get("snippet", "")
                entry["note"] = "Failed to fetch full page content, showing search snippet only"
            elif "error" in page_data:
                entry["content"] = result.get("snippet", "")
                entry["note"] = f"Could not fetch page: {page_data['error']}. Showing search snippet only"
            else:
                entry["content"] = page_data.get("content", "")

            combined_results.append(entry)

        return {
            "query": query,
            "results": combined_results,
            "instruction": (
                "Review the full page content from each result to provide "
                "the user with a comprehensive and accurate answer. "
                "Cite sources when possible. If the results don't fully "
                "answer the question, you may use the open_url tool to "
                "visit specific pages for more detail, or perform another "
                "search with a refined query."
            ),
        }

    async def _search_searxng(
        self, base_url: str, query: str, num_results: int, timeout: int
    ) -> list[dict]:
        """Query SearXNG and return result metadata."""
        session = async_get_clientsession(self.hass)

        params = {
            "q": query,
            "format": "json",
        }

        async with session.get(
            f"{base_url}/search",
            params=params,
            headers={"Accept": "application/json"},
            timeout=timeout,
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"SearXNG returned HTTP {resp.status}"
                )

            data = await resp.json()
            results = []

            for item in data.get("results", [])[:num_results]:
                results.append(
                    {
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("content", ""),
                    }
                )

            return results


class OpenUrlTool(llm.Tool):
    """Fetch and extract content from a specific URL."""

    name = "open_url"
    description = (
        "Fetches a web page at the given URL and extracts its text content. "
        "Use this to read the full content of a specific web page, follow links "
        "from search results, or get detailed information from a known URL. "
        "Only works with http/https URLs returning HTML content."
    )
    parameters = vol.Schema(
        {
            vol.Required(
                "url", description="The URL of the web page to fetch"
            ): str,
        }
    )

    def __init__(self, config: dict, hass: HomeAssistant) -> None:
        """Initialize the tool."""
        super().__init__()
        self.config = config
        self.hass = hass

    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: llm.ToolInput,
        llm_context: llm.LLMContext,
    ) -> JsonObjectType:
        """Fetch URL content."""
        url = tool_input.tool_args["url"]
        _LOGGER.info("Fetching URL: %s", url)

        max_content_length = int(
            self.config.get(CONF_MAX_CONTENT_LENGTH, DEFAULT_MAX_CONTENT_LENGTH)
        )
        timeout = int(self.config.get(CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT))

        result = await fetch_page_content(hass, url, max_content_length, timeout)

        if "error" in result:
            return {"url": url, "error": result["error"]}

        return {
            "url": url,
            "content": result.get("content", ""),
            "instruction": (
                "Use the extracted page content to answer the user's question. "
                "Provide a clear, accurate response based on the information found."
            ),
        }
