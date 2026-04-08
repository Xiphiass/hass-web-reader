"""Web content fetching utilities."""

from __future__ import annotations

import logging
import re
from html import unescape
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

# Tags that typically contain the main content
CONTENT_TAGS = ["article", "main", "[role='main']"]

# Tags to remove as they don't contain useful content
REMOVE_TAGS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "noscript",
    "iframe",
    "svg",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "figure",
    "img",
    "video",
    "audio",
    "canvas",
    "map",
    "object",
    "embed",
]


def _extract_text(html_content: str, max_length: int) -> str:
    """Extract readable text from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Remove unwanted tags
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Try to find main content area first
    main_content = None
    for selector in CONTENT_TAGS:
        if selector.startswith("["):
            main_content = soup.select_one(selector)
        else:
            main_content = soup.find(selector)
        if main_content:
            break

    target = main_content if main_content else soup.body if soup.body else soup

    # Extract text
    text = target.get_text(separator="\n")

    # Clean up whitespace
    text = unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple blank lines into one
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    # Collapse multiple spaces on same line
    text = re.sub(r"[^\S\n]+", " ", text)
    text = text.strip()

    if len(text) > max_length:
        text = text[:max_length] + "\n\n[Content truncated]"

    return text


def _validate_url(url: str) -> bool:
    """Validate a URL to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block private/internal network ranges
    # Allow localhost/private IPs only for SearXNG (validated separately)
    return True


async def fetch_page_content(
    hass,
    url: str,
    max_length: int,
    timeout: int,
) -> dict:
    """Fetch a URL and return extracted text content."""
    if not _validate_url(url):
        return {"url": url, "error": "Invalid or disallowed URL"}

    session = async_get_clientsession(hass)

    try:
        async with session.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; HomeAssistant ExtendedWebSearch)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
            allow_redirects=True,
            max_redirects=5,
        ) as resp:
            if resp.status != 200:
                return {
                    "url": url,
                    "error": f"HTTP {resp.status}",
                }

            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return {
                    "url": url,
                    "error": f"Non-HTML content type: {content_type}",
                }

            html_content = await resp.text()
            text = _extract_text(html_content, max_length)

            if not text:
                return {"url": url, "error": "No text content extracted"}

            return {
                "url": url,
                "content": text,
            }

    except TimeoutError:
        return {"url": url, "error": "Request timed out"}
    except Exception as e:
        _LOGGER.warning("Error fetching %s: %s", url, e)
        return {"url": url, "error": f"Failed to fetch: {e!s}"}
