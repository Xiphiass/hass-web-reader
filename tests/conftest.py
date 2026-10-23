"""Fixtures for Web Reader tests."""

import pytest

from custom_components.web_reader.const import (
    CONF_MAX_CONTENT_LENGTH,
    CONF_NUM_RESULTS,
    CONF_REQUEST_TIMEOUT,
    CONF_SEARXNG_URL,
)

SEARXNG_URL = "http://searxng.local:8080"

CONFIG = {
    CONF_SEARXNG_URL: SEARXNG_URL,
    CONF_NUM_RESULTS: 2,
    CONF_MAX_CONTENT_LENGTH: 1000,
    CONF_REQUEST_TIMEOUT: 10,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests."""
    return
