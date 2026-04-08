"""LLM API registration for Extended Web Search."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import API_NAME, DOMAIN
from .tools import OpenUrlTool, SearchWebTool

_LOGGER = logging.getLogger(__name__)

API_PROMPT = (
    "You have access to Extended Web Search tools that let you search the web "
    "and retrieve full page content from websites.\n\n"
    "Use `search_web` to find information by performing a web search query. "
    "This will search with SearXNG and automatically fetch the full text content "
    "from each result page — not just snippets.\n\n"
    "Use `open_url` to fetch the full text content of a specific web page URL. "
    "This is useful for following links found in search results or reading a "
    "page the user has referenced.\n\n"
    "Guidelines:\n"
    "- Always use these tools to look up current events, factual questions, "
    "or anything you're not certain about.\n"
    "- Do not rely solely on your training data for time-sensitive information.\n"
    "- Cite the source URL when providing information from search results.\n"
    "- If results are insufficient, refine your search query and try again."
)


class ExtendedWebSearchAPI(llm.API):
    """LLM API that provides extended web search tools."""

    def __init__(
        self, hass: HomeAssistant, config: dict[str, Any]
    ) -> None:
        """Initialize the API."""
        super().__init__(
            hass=hass,
            id=DOMAIN,
            name=API_NAME,
        )
        self.config = config

    async def async_get_api_instance(
        self, llm_context: llm.LLMContext
    ) -> llm.APIInstance:
        """Return an instance of this API."""
        tools: list[llm.Tool] = [
            SearchWebTool(self.config, self.hass),
            OpenUrlTool(self.config, self.hass),
        ]
        return llm.APIInstance(
            api=self,
            api_prompt=API_PROMPT,
            llm_context=llm_context,
            tools=tools,
        )


async def setup_api(hass: HomeAssistant, config: dict[str, Any]) -> None:
    """Register the LLM API with Home Assistant."""
    if DOMAIN in hass.data and "unregister" in hass.data[DOMAIN]:
        await cleanup_api(hass)

    hass.data.setdefault(DOMAIN, {})

    api = ExtendedWebSearchAPI(hass, config)
    hass.data[DOMAIN]["api"] = api
    hass.data[DOMAIN]["config"] = config.copy()

    try:
        unreg = llm.async_register_api(hass, api)
        hass.data[DOMAIN]["unregister"] = unreg
        _LOGGER.info("Extended Web Search LLM API registered successfully")
    except Exception:
        _LOGGER.exception("Failed to register Extended Web Search LLM API")
        raise


async def cleanup_api(hass: HomeAssistant) -> None:
    """Unregister the LLM API."""
    if DOMAIN in hass.data:
        unreg = hass.data[DOMAIN].get("unregister")
        if unreg:
            try:
                unreg()
            except Exception:
                _LOGGER.debug("Error unregistering LLM API", exc_info=True)

        hass.data.pop(DOMAIN, None)
