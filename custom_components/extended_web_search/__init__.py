"""Extended Web Search integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import ADDON_NAME, DOMAIN
from .llm_api import cleanup_api, setup_api

__all__ = ["DOMAIN"]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Extended Web Search integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Extended Web Search from a config entry."""
    _LOGGER.info("Setting up %s for entry: %s", ADDON_NAME, entry.entry_id)
    config = {**entry.data, **(entry.options or {})}
    await setup_api(hass, config)
    _LOGGER.info("%s successfully set up", ADDON_NAME)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading %s for entry: %s", ADDON_NAME, entry.entry_id)
    await cleanup_api(hass)
    _LOGGER.info("%s successfully unloaded", ADDON_NAME)
    return True
