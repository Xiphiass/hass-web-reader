"""Tests for the config flow and setup."""

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import llm
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.extended_web_search.const import (
    CONF_NUM_RESULTS,
    CONF_SEARXNG_URL,
    DOMAIN,
)

from .conftest import CONFIG, SEARXNG_URL

USER_INPUT = {**CONFIG, CONF_SEARXNG_URL: f"  {SEARXNG_URL}/ "}


async def test_user_flow(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test a successful setup normalizes the URL."""
    aioclient_mock.get(f"{SEARXNG_URL}/search", json={"results": []})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == CONFIG


@pytest.mark.parametrize(
    ("mock_kwargs", "user_url", "error"),
    [
        ({"status": 403}, SEARXNG_URL, "json_disabled"),
        ({"text": "<html></html>"}, SEARXNG_URL, "json_disabled"),
        ({"status": 500}, SEARXNG_URL, "cannot_connect"),
        ({"exc": TimeoutError()}, SEARXNG_URL, "cannot_connect"),
        ({}, "searxng.local:8080", "invalid_url"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    user_url: str,
    error: str,
) -> None:
    """Test setup errors are shown on the form."""
    aioclient_mock.get(f"{SEARXNG_URL}/search", **mock_kwargs)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONFIG, CONF_SEARXNG_URL: user_url}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_SEARXNG_URL: error}


async def test_single_instance(hass: HomeAssistant) -> None:
    """Test only one entry can be created."""
    MockConfigEntry(domain=DOMAIN, data=CONFIG).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_setup_unload_and_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test the API is registered, reloaded on options change and removed."""
    aioclient_mock.get(f"{SEARXNG_URL}/search", json={"results": []})
    entry = MockConfigEntry(domain=DOMAIN, data=CONFIG)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert DOMAIN in {api.id for api in llm.async_get_apis(hass)}

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**CONFIG, CONF_NUM_RESULTS: 7}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_NUM_RESULTS] == 7
    assert entry.state is ConfigEntryState.LOADED
    api = next(api for api in llm.async_get_apis(hass) if api.id == DOMAIN)
    assert api.config[CONF_NUM_RESULTS] == 7

    session = entry.runtime_data.fetch_session
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert DOMAIN not in {api.id for api in llm.async_get_apis(hass)}
    assert session.closed
