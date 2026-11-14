"""SSRF-resistant HTTP fetching for external news content.

Defences (docs/SECURITY.md T7):
* only http/https, default ports, no credentials in URLs, no IP-literal hosts;
* the host must be on the source's approved domain list — re-checked on every redirect;
* DNS is resolved once, inside the connection backend, and every resolved address must be
  public (no loopback, private, link-local/cloud-metadata, CGNAT, multicast, reserved).
  The socket connects to that validated IP, so a second (rebinding) lookup never happens.
  TLS still verifies the certificate against the original hostname;
* timeouts, a response-size cap, a content-type allow-list and a redirect limit.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpcore

Resolver = Callable[[str, int], list[str]]
IpPolicy = Callable[[str], bool]

ALLOWED_CONTENT_TYPES = ("xml", "rss", "atom", "html", "json", "text/plain")


class FetchError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


def system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("dns_failure", f"Could not resolve {host}") from exc
    return list(dict.fromkeys(str(info[4][0]) for info in infos))


def is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def normalise_domain(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def host_allowed(host: str, allowed_domains: Iterable[str]) -> bool:
    host = normalise_domain(host)
    for d in allowed_domains:
        d = normalise_domain(d)
        if d and (host == d or host.endswith("." + d)):
            return True
    return False


def validate_url(
    url: str, allowed_domains: Iterable[str], allowed_ports: Iterable[int] = (80, 443)
) -> str:
    """Return the lower-cased host if the URL may be requested, else raise FetchError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise FetchError("invalid_url", "Malformed URL") from exc
    if parts.scheme not in ("http", "https"):
        raise FetchError("invalid_url", "Only http and https URLs are allowed")
    if parts.username or parts.password:
        raise FetchError("invalid_url", "Credentials in URLs are not allowed")
    host = normalise_domain(parts.hostname or "")
    if not host:
        raise FetchError("invalid_url", "URL has no host")
    if port is not None and port not in allowed_ports:
        raise FetchError("invalid_url", "Non-standard ports are not allowed")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise FetchError("domain_not_allowed", "IP-address URLs are not allowed")
    if not host_allowed(host, allowed_domains):
        raise FetchError("domain_not_allowed", f"{host} is not an approved domain")
    return host


class _GuardedBackend(httpcore.NetworkBackend):
    """Resolves, validates and pins the destination IP for every new connection."""

    def __init__(self, resolver: Resolver, ip_allowed: IpPolicy) -> None:
        self._inner = httpcore.SyncBackend()
        self._resolver = resolver
        self._ip_allowed = ip_allowed

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.NetworkStream:
        addresses = self._resolver(host, port)
        if not addresses:
            raise FetchError("dns_failure", f"No addresses for {host}")
        blocked = [a for a in addresses if not self._ip_allowed(a)]
        if blocked:
            # Refuse if *any* record is internal: mixed answers are a rebinding signal.
            raise FetchError("blocked_address", f"{host} resolves to a non-public address")
        return self._inner.connect_tcp(
            addresses[0],
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(self, *args: Any, **kwargs: Any) -> httpcore.NetworkStream:
        raise FetchError("blocked_address", "Unix sockets are not allowed")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class SafeFetcher:
    def __init__(
        self,
        *,
        resolver: Resolver = system_resolver,
        ip_allowed: IpPolicy = is_public_ip,
        timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 3,
        allowed_ports: Iterable[int] = (80, 443),
        user_agent: str = "JanakiNewsroomBot/0.1 (+https://janaki-newsroom.example.com/bot)",
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.allowed_ports = tuple(allowed_ports)
        self.user_agent = user_agent
        self._pool = httpcore.ConnectionPool(
            network_backend=_GuardedBackend(resolver, ip_allowed),
            retries=0,
            max_connections=10,
        )

    def close(self) -> None:
        self._pool.close()

    def fetch(self, url: str, allowed_domains: Iterable[str]) -> FetchResult:
        allowed = [normalise_domain(d) for d in allowed_domains]
        current = url
        for _ in range(self.max_redirects + 1):
            validate_url(current, allowed, self.allowed_ports)
            status, headers, body = self._request(current)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("location")
                if not location:
                    raise FetchError("http_status", f"Redirect without Location ({status})")
                current = urljoin(current, location)
                continue
            if status >= 400:
                raise FetchError("http_status", f"HTTP {status}", status=status)
            ctype = headers.get("content-type", "").lower()
            if not any(t in ctype for t in ALLOWED_CONTENT_TYPES):
                raise FetchError("bad_content_type", f"Unexpected content type: {ctype[:80]}")
            return FetchResult(
                url=url, final_url=current, status=status, content_type=ctype, body=body
            )
        raise FetchError("too_many_redirects", "Too many redirects")

    def _request(self, url: str) -> tuple[int, dict[str, str], bytes]:
        timeout = {
            "connect": self.timeout,
            "read": self.timeout,
            "write": self.timeout,
            "pool": self.timeout,
        }
        headers = [
            (b"User-Agent", self.user_agent.encode()),
            (
                b"Accept",
                b"application/rss+xml, application/atom+xml, application/xml, "
                b"text/xml, text/html;q=0.8, */*;q=0.1",
            ),
            (b"Accept-Encoding", b"identity"),
        ]
        try:
            with self._pool.stream(
                "GET", url, headers=headers, extensions={"timeout": timeout}
            ) as resp:
                hdrs = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in resp.headers}
                length = hdrs.get("content-length", "")
                if length.isdigit() and int(length) > self.max_bytes:
                    raise FetchError("too_large", "Response exceeds size limit")
                chunks: list[bytes] = []
                size = 0
                if resp.status < 300 or resp.status >= 400:
                    for chunk in resp.iter_stream():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise FetchError("too_large", "Response exceeds size limit")
                        chunks.append(chunk)
                return resp.status, hdrs, b"".join(chunks)
        except FetchError:
            raise
        except httpcore.TimeoutException as exc:
            raise FetchError("timeout", "Request timed out") from exc
        except (httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise FetchError("network", f"Network error: {type(exc).__name__}") from exc
