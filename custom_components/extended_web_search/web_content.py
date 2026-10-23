"""Web content fetching utilities."""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp.abc import AbstractResolver, ResolveResult
from aiohttp.resolver import DefaultResolver
from bs4 import BeautifulSoup
from homeassistant.core import HomeAssistant

from .const import MAX_DOWNLOAD_BYTES, MAX_REDIRECTS

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

# Elements that contain the main content, in order of preference
CONTENT_SELECTORS = ["main", "[role='main']"]

# Tags to remove as they don't contain useful content
REMOVE_TAGS = [
    "script",
    "style",
    "template",
    "nav",
    "aside",
    "noscript",
    "iframe",
    "svg",
    "button",
    "input",
    "select",
    "textarea",
    "img",
    "picture",
    "video",
    "audio",
    "canvas",
    "map",
    "object",
    "embed",
]

# Site-wide chrome; only removed when not part of the main content
LAYOUT_TAGS = ["header", "footer"]


class DisallowedAddressError(OSError):
    """Raised when a host resolves to a non-public address."""


def is_public_ip(address: str) -> bool:
    """Return True if the address is publicly routable."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicOnlyResolver(AbstractResolver):
    """Resolver that refuses hostnames resolving to non-public addresses.

    Checking at resolve time (rather than before the request) also covers
    redirects and DNS rebinding, because aiohttp connects to exactly the
    addresses returned here.
    """

    def __init__(self) -> None:
        """Initialize the resolver."""
        self._resolver = DefaultResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[ResolveResult]:
        """Resolve a host and reject any non-public result."""
        results = await self._resolver.resolve(host, port, family)
        for result in results:
            if not is_public_ip(result["host"]):
                raise DisallowedAddressError(
                    f"{host} resolves to non-public address {result['host']}"
                )
        return results

    async def close(self) -> None:
        """Close the resolver."""
        await self._resolver.close()


def create_fetch_session() -> aiohttp.ClientSession:
    """Create the session used to fetch untrusted web pages."""
    return aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=PublicOnlyResolver()),
        headers={"User-Agent": USER_AGENT},
    )


def validate_url(url: str) -> str | None:
    """Return an error message if the URL may not be fetched, else None.

    Literal IP addresses bypass the resolver, so they are checked here.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
    except ValueError:
        return "Invalid URL"

    if parsed.scheme not in ("http", "https"):
        return "Only http and https URLs are supported"
    if not hostname:
        return "Invalid URL"

    try:
        ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        return None  # A hostname; checked by PublicOnlyResolver
    if not is_public_ip(hostname):
        return "Access to private or local network addresses is not allowed"
    return None


def _decompose_outside_content(soup: BeautifulSoup) -> None:
    """Remove noise tags, keeping headers/footers inside articles."""
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    for tag in soup.find_all(LAYOUT_TAGS):
        if tag.find_parent(["article", "main"]) is None:
            tag.decompose()


def extract_text(raw: bytes, encoding: str | None, max_length: int) -> str:
    """Extract readable text from HTML content.

    CPU bound; run in an executor.
    """
    soup = BeautifulSoup(raw, "html.parser", from_encoding=encoding)
    _decompose_outside_content(soup)

    target = None
    for selector in CONTENT_SELECTORS:
        if target := soup.select_one(selector):
            break
    if target is None:
        # A single article is the main content; several are usually a listing
        articles = soup.find_all("article")
        if len(articles) == 1:
            target = articles[0]
    if target is None:
        target = soup.body or soup

    text = target.get_text(separator="\n")

    # Collapse runs of spaces/tabs on the same line
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse multiple blank lines into one
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = text.strip()

    if len(text) > max_length:
        text = text[:max_length]
    return text


async def _download(
    session: aiohttp.ClientSession, url: str, timeout: aiohttp.ClientTimeout
) -> tuple[str, bytes, str | None] | dict[str, Any]:
    """Download a page, following and validating redirects manually.

    Returns (final_url, body, charset) or an error dict.
    """
    for _ in range(MAX_REDIRECTS + 1):
        if error := validate_url(url):
            return {"error": error}

        async with session.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.5",
            },
            allow_redirects=False,
        ) as resp:
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.headers.get("Location")
                if not location:
                    return {"error": f"HTTP {resp.status} without Location"}
                url = urljoin(url, location)
                continue

            if resp.status != 200:
                return {"error": f"HTTP {resp.status}"}

            content_type = resp.headers.get("Content-Type", "").lower()
            if not content_type.startswith(HTML_CONTENT_TYPES):
                return {"error": f"Non-HTML content type: {content_type or 'unknown'}"}

            if (resp.content_length or 0) > MAX_DOWNLOAD_BYTES:
                # Still read the start; it usually holds the content
                _LOGGER.debug("Truncating large page %s", url)

            body = bytearray()
            async for chunk in resp.content.iter_chunked(65536):
                body += chunk
                if len(body) >= MAX_DOWNLOAD_BYTES:
                    del body[MAX_DOWNLOAD_BYTES:]
                    break

            return url, bytes(body), resp.charset

    return {"error": "Too many redirects"}


async def fetch_page_content(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    url: str,
    max_length: int,
    timeout: float,
) -> dict[str, Any]:
    """Fetch a URL and return extracted text content.

    Returns {"url", "content"} on success or {"url", "error"} on failure.
    """
    try:
        result = await _download(session, url, aiohttp.ClientTimeout(total=timeout))
    except TimeoutError:
        return {"url": url, "error": "Request timed out"}
    except aiohttp.ClientConnectorError as err:
        # aiohttp wraps resolver errors; unwrap to report blocked addresses
        if isinstance(err.os_error, DisallowedAddressError):
            return {
                "url": url,
                "error": "Access to private or local network addresses is not allowed",
            }
        _LOGGER.debug("Error fetching %s: %s", url, err)
        return {"url": url, "error": f"Failed to fetch: {err!s}"}
    except (aiohttp.ClientError, OSError, ValueError) as err:
        _LOGGER.debug("Error fetching %s: %s", url, err)
        return {"url": url, "error": f"Failed to fetch: {err!s}"}

    if isinstance(result, dict):
        return {"url": url, **result}

    final_url, body, charset = result
    text = await hass.async_add_executor_job(extract_text, body, charset, max_length)
    if not text:
        return {"url": final_url, "error": "No text content extracted"}

    return {"url": final_url, "content": text}
