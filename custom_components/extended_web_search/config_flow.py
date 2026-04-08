"""Config flow for the Extended Web Search integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
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

_LOGGER = logging.getLogger(__name__)


def get_setup_schema(defaults: dict | None = None) -> vol.Schema:
    """Return the schema for the setup form."""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SEARXNG_URL,
                default=defaults.get(CONF_SEARXNG_URL, ""),
            ): str,
            vol.Required(
                CONF_NUM_RESULTS,
                default=defaults.get(CONF_NUM_RESULTS, DEFAULT_NUM_RESULTS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1,
                    max=10,
                    step=1,
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_MAX_CONTENT_LENGTH,
                default=defaults.get(
                    CONF_MAX_CONTENT_LENGTH, DEFAULT_MAX_CONTENT_LENGTH
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1000,
                    max=50000,
                    step=1000,
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_REQUEST_TIMEOUT,
                default=defaults.get(
                    CONF_REQUEST_TIMEOUT, DEFAULT_REQUEST_TIMEOUT
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5,
                    max=60,
                    step=5,
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


class ExtendedWebSearchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Extended Web Search."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle the initial setup step."""
        errors = {}

        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=get_setup_schema(),
                errors=errors,
            )

        # Validate SearXNG URL
        url = user_input.get(CONF_SEARXNG_URL, "").rstrip("/")
        if not url:
            errors[CONF_SEARXNG_URL] = "url_required"
            return self.async_show_form(
                step_id="user",
                data_schema=get_setup_schema(user_input),
                errors=errors,
            )

        user_input[CONF_SEARXNG_URL] = url
        user_input[CONF_NUM_RESULTS] = int(user_input[CONF_NUM_RESULTS])
        user_input[CONF_MAX_CONTENT_LENGTH] = int(
            user_input[CONF_MAX_CONTENT_LENGTH]
        )
        user_input[CONF_REQUEST_TIMEOUT] = int(user_input[CONF_REQUEST_TIMEOUT])

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=ADDON_NAME,
            data=user_input,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return ExtendedWebSearchOptionsFlow(config_entry)


class ExtendedWebSearchOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle options flow for Extended Web Search."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__()
        self._config_entry = config_entry

    @property
    def config_entry(self) -> config_entries.ConfigEntry:
        """Return the config entry."""
        return self._config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        """Handle options flow."""
        if user_input is not None:
            url = user_input.get(CONF_SEARXNG_URL, "").rstrip("/")
            user_input[CONF_SEARXNG_URL] = url
            user_input[CONF_NUM_RESULTS] = int(user_input[CONF_NUM_RESULTS])
            user_input[CONF_MAX_CONTENT_LENGTH] = int(
                user_input[CONF_MAX_CONTENT_LENGTH]
            )
            user_input[CONF_REQUEST_TIMEOUT] = int(
                user_input[CONF_REQUEST_TIMEOUT]
            )
            return self.async_create_entry(data=user_input)

        defaults = {**self.config_entry.data, **(self.config_entry.options or {})}
        schema = get_setup_schema(defaults)
        schema = self.add_suggested_values_to_schema(schema, defaults)

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
        )
