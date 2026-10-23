"""Tests for page fetching and text extraction."""

from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.extended_web_search import web_content
from custom_components.extended_web_search.web_content import (
    DisallowedAddressError,
    PublicOnlyResolver,
    extract_text,
    fetch_page_content,
    is_public_ip,
    validate_url,
)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("93.184.216.34", True),
        ("2606:2800:220:1:248:1893:25c8:1946", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.1.1", False),
        ("172.16.0.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1%eth0", False),
        ("fd00::1", False),
        ("::ffff:192.168.1.1", False),
        ("224.0.0.1", False),
        ("not-an-ip", False),
    ],
)
def test_is_public_ip(address: str, expected: bool) -> None:
    """Test public address detection."""
    assert is_public_ip(address) is expected


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://example.com/page", True),
        ("http://93.184.216.34/", True),
        ("http://127.0.0.1:8123/api/", False),
        ("http://[::1]/", False),
        ("http://192.168.1.1/", False),
        ("ftp://example.com/", False),
        ("file:///etc/passwd", False),
        ("https://", False),
        ("http://[invalid/", False),
    ],
)
def test_validate_url(url: str, allowed: bool) -> None:
    """Test URL validation."""
    assert (validate_url(url) is None) is allowed


async def test_resolver_rejects_private_results() -> None:
    """Test the resolver refuses hostnames that resolve to private addresses."""
    resolver = PublicOnlyResolver()
    private = [{"hostname": "x", "host": "192.168.1.5", "port": 80}]
    public = [{"hostname": "x", "host": "93.184.216.34", "port": 80}]
    with (
        patch.object(resolver._resolver, "resolve", AsyncMock(return_value=private)),
        pytest.raises(DisallowedAddressError),
    ):
        await resolver.resolve("evil.example", 80)
    with patch.object(resolver._resolver, "resolve", AsyncMock(return_value=public)):
        assert await resolver.resolve("example.com", 80) == public
    await resolver.close()


def test_extract_keeps_form_wrapped_pages() -> None:
    """Test pages wrapped in a single form (ASP.NET WebForms) keep their text."""
    html = b"<html><body><form><p>Opening hours are 9 to 5.</p></form></body></html>"
    assert "Opening hours are 9 to 5." in extract_text(html, None, 1000)


def test_extract_keeps_article_header_drops_site_header() -> None:
    """Test site headers are removed but article headers are kept."""
    html = b"""<html><body>
        <header>Site menu</header>
        <article><header><h1>Article title</h1></header><p>Body</p>
        <figure><figcaption>Caption</figcaption></figure></article>
        <footer>Copyright</footer>
    </body></html>"""
    text = extract_text(html, None, 1000)
    assert "Article title" in text
    assert "Caption" in text
    assert "Site menu" not in text
    assert "Copyright" not in text


def test_extract_keeps_angle_brackets_in_text() -> None:
    """Test escaped markup in text is not stripped."""
    html = b"<html><body><main><p>Use &lt;div&gt; and a &lt; b</p></main></body></html>"
    assert "Use <div> and a < b" in extract_text(html, None, 1000)


def test_extract_listing_page_uses_body() -> None:
    """Test pages with several articles return all of them."""
    html = b"""<html><body>
        <article><p>First story</p></article>
        <article><p>Second story</p></article>
    </body></html>"""
    text = extract_text(html, None, 1000)
    assert "First story" in text
    assert "Second story" in text


def test_extract_prefers_main_and_drops_noise() -> None:
    """Test the main element is used and scripts are dropped."""
    html = b"""<html><body><div>Sidebar</div>
        <main><p>Main text</p><script>alert(1)</script></main></body></html>"""
    assert extract_text(html, None, 1000) == "Main text"


def test_extract_handles_bad_encoding_and_truncates() -> None:
    """Test mis-declared encodings don't fail and output is capped."""
    html = b"<html><body><p>caf\xe9 " + b"x" * 500 + b"</p></body></html>"
    text = extract_text(html, "utf-8", 50)
    assert len(text) == 50


@pytest.fixture
def allow_loopback():
    """Treat the loopback test server as public, but keep 10.0.0.0/8 private."""
    with patch.object(
        web_content, "is_public_ip", side_effect=lambda ip: not ip.startswith("10.")
    ):
        yield


async def _serve(aiohttp_server, routes):
    app = web.Application()
    app.add_routes(routes)
    server = await aiohttp_server(app)
    return f"http://127.0.0.1:{server.port}"


@pytest.mark.usefixtures("socket_enabled")
async def test_fetch_follows_redirects(hass, aiohttp_server, allow_loopback) -> None:
    """Test redirects are followed and the final URL is returned."""

    async def start(request):
        raise web.HTTPFound("/page")

    async def page(request):
        return web.Response(text="<p>Hello</p>", content_type="text/html")

    base = await _serve(aiohttp_server, [web.get("/", start), web.get("/page", page)])
    async with aiohttp.ClientSession() as session:
        result = await fetch_page_content(hass, session, f"{base}/", 1000, 5)
    assert result == {"url": f"{base}/page", "content": "Hello"}


@pytest.mark.usefixtures("socket_enabled")
async def test_fetch_blocks_redirect_to_private(
    hass, aiohttp_server, allow_loopback
) -> None:
    """Test a redirect to a private address is refused."""

    async def start(request):
        raise web.HTTPFound("http://10.0.0.1/admin")

    base = await _serve(aiohttp_server, [web.get("/", start)])
    async with aiohttp.ClientSession() as session:
        result = await fetch_page_content(hass, session, f"{base}/", 1000, 5)
    assert "private" in result["error"]


@pytest.mark.usefixtures("socket_enabled")
async def test_fetch_rejects_non_html(hass, aiohttp_server, allow_loopback) -> None:
    """Test non-HTML responses are refused."""

    async def pdf(request):
        return web.Response(body=b"%PDF", content_type="application/pdf")

    base = await _serve(aiohttp_server, [web.get("/", pdf)])
    async with aiohttp.ClientSession() as session:
        result = await fetch_page_content(hass, session, f"{base}/", 1000, 5)
    assert "Non-HTML" in result["error"]


@pytest.mark.usefixtures("socket_enabled")
async def test_fetch_caps_download_size(hass, aiohttp_server, allow_loopback) -> None:
    """Test only the first MAX_DOWNLOAD_BYTES of a page are read."""

    async def huge(request):
        return web.Response(text="<p>" + "a" * 5000 + "</p>", content_type="text/html")

    base = await _serve(aiohttp_server, [web.get("/", huge)])
    with patch.object(web_content, "MAX_DOWNLOAD_BYTES", 100):
        async with aiohttp.ClientSession() as session:
            result = await fetch_page_content(hass, session, f"{base}/", 10000, 5)
    assert len(result["content"]) < 100


@pytest.mark.usefixtures("socket_enabled")
async def test_fetch_session_blocks_localhost(hass) -> None:
    """Test the real fetch session refuses hostnames resolving to loopback."""
    session = web_content.create_fetch_session()
    try:
        result = await fetch_page_content(
            hass, session, "http://localhost:8123/", 1000, 5
        )
    finally:
        await session.close()
    assert "private" in result["error"]
