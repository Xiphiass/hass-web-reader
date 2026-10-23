"""Web Reader integration for Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm

from .const import DOMAIN
from .llm_api import WebReaderAPI
from .web_content import create_fetch_session

__all__ = ["DOMAIN"]


@dataclass
class RuntimeData:
    """Data held while the config entry is loaded."""

    fetch_session: aiohttp.ClientSession


type WebReaderConfigEntry = ConfigEntry[RuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: WebReaderConfigEntry) -> bool:
    """Set up Web Reader from a config entry."""
    fetch_session = create_fetch_session()
    entry.runtime_data = RuntimeData(fetch_session=fetch_session)
    entry.async_on_unload(fetch_session.close)

    config = {**entry.data, **entry.options}
    entry.async_on_unload(
        llm.async_register_api(hass, WebReaderAPI(hass, config, fetch_session))
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WebReaderConfigEntry) -> bool:
    """Unload a config entry."""
    return True
