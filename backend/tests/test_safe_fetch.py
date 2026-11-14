"""SSRF defences. A real local HTTP server is used; DNS is substituted so that the
hostname feeds.example.com is pinned to 127.0.0.1 only when the test explicitly allows it."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.modules.discovery.safe_fetch import FetchError, SafeFetcher, is_public_ip, validate_url

DOMAINS = ["example.com"]


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        port = self.server.server_address[1]
        routes = {
            "/feed": (200, "application/rss+xml", b"<rss></rss>", {}),
            "/big": (200, "application/rss+xml", b"x" * 5000, {}),
            "/binary": (200, "application/octet-stream", b"MZ", {}),
            "/error": (500, "text/html", b"boom", {}),
            "/to-evil": (302, "text/html", b"", {"Location": "http://evil.example.net/feed"}),
            "/to-metadata": (
                302,
                "text/html",
                b"",
                {"Location": "http://169.254.169.254/latest/meta-data/"},
            ),
            "/to-feed": (
                301,
                "text/html",
                b"",
                {"Location": f"http://feeds.example.com:{port}/feed"},
            ),
            "/loop": (302, "text/html", b"", {"Location": "/loop"}),
        }
        status, ctype, body, extra = routes.get(self.path, (404, "text/plain", b"", {}))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server() -> Iterator[int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def _loopback_fetcher(port: int, **kw: object) -> SafeFetcher:
    """Pins feeds.example.com to 127.0.0.1 and permits loopback for this test only."""
    return SafeFetcher(
        resolver=lambda host, p: ["127.0.0.1"],
        ip_allowed=lambda ip: ip == "127.0.0.1",
        allowed_ports=(port,),
        **kw,
    )


@pytest.mark.parametrize(
    "url,code",
    [
        ("ftp://example.com/feed", "invalid_url"),
        ("file:///etc/passwd", "invalid_url"),
        ("http://user:pw@example.com/", "invalid_url"),
        ("http://example.com:8080/", "invalid_url"),
        ("http://127.0.0.1/", "domain_not_allowed"),
        ("http://[::1]/", "domain_not_allowed"),
        ("http://169.254.169.254/latest/meta-data/", "domain_not_allowed"),
        ("http://example.com.evil.net/", "domain_not_allowed"),
        ("http://notexample.com/", "domain_not_allowed"),
    ],
)
def test_validate_url_rejects(url: str, code: str) -> None:
    with pytest.raises(FetchError) as exc:
        validate_url(url, DOMAINS)
    assert exc.value.code == code


def test_validate_url_accepts_domain_and_subdomain() -> None:
    assert validate_url("https://example.com/rss", DOMAINS) == "example.com"
    assert validate_url("https://News.Example.com./rss", DOMAINS) == "news.example.com"


@pytest.mark.parametrize(
    "ip,public",
    [
        ("8.8.8.8", True),
        ("2606:4700:4700::1111", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("172.16.0.1", False),
        ("192.168.1.1", False),
        ("169.254.169.254", False),
        ("100.64.0.1", False),
        ("0.0.0.0", False),
        ("::1", False),
        ("fc00::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),
        ("224.0.0.1", False),
    ],
)
def test_is_public_ip(ip: str, public: bool) -> None:
    assert is_public_ip(ip) is public


def test_hostname_resolving_to_internal_address_is_blocked() -> None:
    f = SafeFetcher(resolver=lambda host, port: ["127.0.0.1"])
    with pytest.raises(FetchError) as exc:
        f.fetch("http://feeds.example.com/feed", DOMAINS)
    assert exc.value.code == "blocked_address"


def test_mixed_public_and_private_dns_answer_is_blocked() -> None:
    f = SafeFetcher(resolver=lambda host, port: ["93.184.216.34", "10.0.0.5"])
    with pytest.raises(FetchError) as exc:
        f.fetch("http://feeds.example.com/feed", DOMAINS)
    assert exc.value.code == "blocked_address"


def test_fetch_connects_to_pinned_ip(server: int) -> None:
    res = _loopback_fetcher(server).fetch(f"http://feeds.example.com:{server}/feed", DOMAINS)
    assert res.status == 200 and res.body == b"<rss></rss>"


def test_redirect_within_allowed_domain_is_followed(server: int) -> None:
    res = _loopback_fetcher(server).fetch(f"http://feeds.example.com:{server}/to-feed", DOMAINS)
    assert res.final_url.endswith("/feed") and res.body == b"<rss></rss>"


@pytest.mark.parametrize(
    "path,code",
    [
        ("/to-evil", "domain_not_allowed"),
        ("/to-metadata", "domain_not_allowed"),
        ("/loop", "too_many_redirects"),
        ("/big", "too_large"),
        ("/binary", "bad_content_type"),
        ("/error", "http_status"),
    ],
)
def test_fetch_failures(server: int, path: str, code: str) -> None:
    f = _loopback_fetcher(server, max_bytes=1000)
    with pytest.raises(FetchError) as exc:
        f.fetch(f"http://feeds.example.com:{server}{path}", DOMAINS)
    assert exc.value.code == code
