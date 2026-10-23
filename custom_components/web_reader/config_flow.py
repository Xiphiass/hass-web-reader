"""Config flow for the Web Reader integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ADDON_NAME,
    CONF_MAX_CONTENT_LENGTH,
    CONF_NUM_RESULTS,
    CONF_REQUEST_TIMEOUT,
    CONF_SEARXNG_URL,
    DEFAULT_MAX_CONTENT_LENGTH,
    DEFAULT_NUM_RESULTS,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
)
from .searxng import (
    SearxngError,
    SearxngJsonDisabledError,
    async_search,
    normalize_base_url,
)

_LOGGER = logging.getLogger(__name__)


def get_schema() -> vol.Schema:
    """Return the schema for the setup and options forms."""
    return vol.Schema(
        {
            vol.Required(CONF_SEARXNG_URL): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
            vol.Required(CONF_NUM_RESULTS, default=DEFAULT_NUM_RESULTS): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=10, step=1, mode=NumberSelectorMode.SLIDER
                )
            ),
            vol.Required(
                CONF_MAX_CONTENT_LENGTH, default=DEFAULT_MAX_CONTENT_LENGTH
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1000, max=50000, step=1000, mode=NumberSelectorMode.SLIDER
                )
            ),
            vol.Required(
                CONF_REQUEST_TIMEOUT, default=DEFAULT_REQUEST_TIMEOUT
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5, max=60, step=5, mode=NumberSelectorMode.SLIDER
                )
            ),
        }
    )


async def validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Normalize the input and test the SearXNG server.

    Returns the normalized input and a dict of form errors.
    """
    data = {
        CONF_SEARXNG_URL: user_input[CONF_SEARXNG_URL],
        CONF_NUM_RESULTS: int(user_input[CONF_NUM_RESULTS]),
        CONF_MAX_CONTENT_LENGTH: int(user_input[CONF_MAX_CONTENT_LENGTH]),
        CONF_REQUEST_TIMEOUT: int(user_input[CONF_REQUEST_TIMEOUT]),
    }

    url = normalize_base_url(user_input[CONF_SEARXNG_URL])
    if url is None:
        return data, {CONF_SEARXNG_URL: "invalid_url"}
    data[CONF_SEARXNG_URL] = url

    try:
        await async_search(
            async_get_clientsession(hass),
            url,
            "home assistant",
            timeout=data[CONF_REQUEST_TIMEOUT],
        )
    except SearxngJsonDisabledError:
        return data, {CONF_SEARXNG_URL: "json_disabled"}
    except (TimeoutError, aiohttp.ClientError, SearxngError) as err:
        _LOGGER.debug("Cannot connect to SearXNG at %s: %s", url, err)
        return data, {CONF_SEARXNG_URL: "cannot_connect"}
    return data, {}


class WebReaderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Web Reader."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial setup step."""
        errors: dict[str, str] = {}
        suggested: dict[str, Any] = {}

        if user_input is not None:
            data, errors = await validate_input(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title=ADDON_NAME, data=data)
            suggested = data

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(get_schema(), suggested),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> WebReaderOptionsFlow:
        """Return the options flow."""
        return WebReaderOptionsFlow()


class WebReaderOptionsFlow(OptionsFlowWithReload):
    """Handle options flow for Web Reader."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""
        errors: dict[str, str] = {}
        suggested = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            data, errors = await validate_input(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=data)
            suggested = data

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(get_schema(), suggested),
            errors=errors,
        )
