"""Client for a Payload CMS 3 REST API, authenticated as an *integration* with an API key.

The CMS address is configured by a tenant, so every request goes through the same SSRF guard as
news fetching: public addresses only (DNS resolved and pinned per connection), no redirects,
http(s) on standard ports, size-capped responses. Private addresses are allowed only when
``CMS_ALLOW_PRIVATE_HOSTS`` is set, which the settings refuse outside development and tests.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpcore

from app.modules.discovery.safe_fetch import (
    FetchError,
    Resolver,
    _GuardedBackend,
    is_public_ip,
    system_resolver,
    validate_url,
)

MAX_RESPONSE_BYTES = 2_000_000
# (method, url, headers, body) -> (status, body)
Transport = Callable[[str, str, dict[str, str], bytes | None], tuple[int, bytes]]


class CmsError(Exception):
    """``retryable`` errors (network, 5xx, rate limits) are tried again on the next run."""

    def __init__(self, code: str, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.retryable, self.status = code, message, retryable, status


@dataclass(frozen=True)
class CmsTarget:
    base_url: str  # scheme://host[:port], no trailing slash
    host: str
    port: int


def parse_base_url(url: str, *, allow_private: bool) -> CmsTarget:
    """Validate a tenant-supplied CMS address. Returns its normalised origin."""
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" and not allow_private:
        raise CmsError("invalid_url", "The CMS address must start with https://", retryable=False)
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise CmsError(
            "invalid_url",
            "Give only the site address, e.g. https://example.com",
            retryable=False,
        )
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        host = validate_url(
            url,
            [parts.hostname or ""],
            allowed_ports=(80, 443, port) if allow_private else (80, 443),
        )
    except (FetchError, ValueError) as exc:
        raise CmsError("invalid_url", f"Invalid CMS address: {exc}", retryable=False) from exc
    return CmsTarget(base_url=f"{parts.scheme}://{parts.netloc.lower()}", host=host, port=port)


def _pool_transport(resolver: Resolver, allow_private: bool, timeout: float) -> Transport:
    pool = httpcore.ConnectionPool(
        network_backend=_GuardedBackend(
            resolver, (lambda _ip: True) if allow_private else is_public_ip
        ),
        retries=0,
        max_connections=4,
    )
    t = {"connect": timeout, "read": timeout, "write": timeout, "pool": timeout}

    def send(
        method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        with pool.stream(
            method, url, headers=list(headers.items()), content=body, extensions={"timeout": t}
        ) as resp:
            chunks, size = [], 0
            for chunk in resp.iter_stream():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise CmsError("too_large", "CMS response too large", retryable=False)
                chunks.append(chunk)
            return resp.status, b"".join(chunks)

    return send


def _multipart(fields: dict[str, str], filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "janaki" + secrets.token_hex(12)
    out = bytearray()
    for name, value in fields.items():
        out += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += value.encode() + b"\r\n"
    safe_name = "".join(ch for ch in filename if ch.isalnum() or ch in "._-")[:100] or "image"
    out += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode()
    out += data + f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


class PayloadClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        allow_private: bool = False,
        timeout: float = 20.0,
        resolver: Resolver = system_resolver,
        transport: Transport | None = None,
        collection: str = "integrations",
    ) -> None:
        self.target = parse_base_url(base_url, allow_private=allow_private)
        self._auth = f"{collection} API-Key {api_key}"
        self._send = transport or _pool_transport(resolver, allow_private, timeout)

    # -- low level ---------------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        url = self.target.base_url + path + (f"?{urlencode(query)}" if query else "")
        headers = {
            "Authorization": self._auth,
            "Accept": "application/json",
            "User-Agent": "JanakiNewsroom/0.7",
            "Host": urlsplit(self.target.base_url).netloc,
        }
        if payload is not None:
            body = json.dumps(payload).encode()
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        if body is not None:
            headers["Content-Length"] = str(len(body))
        try:
            status, raw = self._send(method, url, headers, body)
        except CmsError:
            raise
        except FetchError as exc:
            raise CmsError(exc.code, exc.message, retryable=exc.code == "dns_failure") from exc
        except (httpcore.TimeoutException, httpcore.NetworkError, httpcore.ProtocolError) as exc:
            raise CmsError(
                "network", f"Could not reach the CMS ({type(exc).__name__})", retryable=True
            ) from exc
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if 300 <= status < 400:
            raise CmsError(
                "redirect",
                "The CMS answered with a redirect; check the address",
                retryable=False,
                status=status,
            )
        if status in (401, 403):
            raise CmsError(
                "unauthorized",
                "The CMS refused the API key (wrong key, or the integration is inactive)",
                retryable=False,
                status=status,
            )
        if status == 429 or status >= 500:
            raise CmsError(
                "unavailable", f"CMS unavailable (HTTP {status})", retryable=True, status=status
            )
        return status, data

    @staticmethod
    def _error_message(data: dict[str, Any]) -> str:
        errors = data.get("errors")
        if isinstance(errors, list) and errors and isinstance(errors[0], dict):
            msg = str(errors[0].get("message", ""))
            fields = (
                errors[0].get("data", {}).get("errors")
                if isinstance(errors[0].get("data"), dict)
                else None
            )
            if isinstance(fields, list) and fields:
                msg += ": " + "; ".join(
                    f"{f.get('path')}: {f.get('message')}" for f in fields if isinstance(f, dict)
                )
            return msg[:400]
        return str(data.get("message", "rejected"))[:400]

    def _expect_doc(self, status: int, data: dict[str, Any], what: str) -> dict[str, Any]:
        if status in (200, 201) and isinstance(data.get("doc"), dict):
            return data["doc"]
        raise CmsError(
            "rejected",
            f"The CMS rejected the {what}: {self._error_message(data)}",
            retryable=False,
            status=status,
        )

    # -- operations --------------------------------------------------------------------------

    def find_article_by_ref(self, ref: str) -> dict[str, Any] | None:
        status, data = self._request(
            "GET",
            "/api/articles",
            query={"where[newsroomRef][equals]": ref, "depth": "0", "limit": "1"},
        )
        if status != 200:
            raise CmsError(
                "rejected",
                f"Lookup failed: {self._error_message(data)}",
                retryable=False,
                status=status,
            )
        docs = data.get("docs") or []
        return docs[0] if docs and isinstance(docs[0], dict) else None

    def get_article(self, remote_id: str) -> dict[str, Any] | None:
        status, data = self._request("GET", f"/api/articles/{remote_id}", query={"depth": "0"})
        if status == 404:
            return None
        if status != 200:
            raise CmsError(
                "rejected",
                f"Lookup failed: {self._error_message(data)}",
                retryable=False,
                status=status,
            )
        return data

    def create_article(self, article: dict[str, Any]) -> dict[str, Any]:
        status, data = self._request("POST", "/api/articles", query={"depth": "0"}, payload=article)
        return self._expect_doc(status, data, "draft")

    def upload_media(
        self, *, filename: str, data: bytes, mime: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        body, ctype = _multipart({"_payload": json.dumps(fields)}, filename, data, mime)
        status, resp = self._request(
            "POST", "/api/media", query={"depth": "0"}, body=body, content_type=ctype
        )
        return self._expect_doc(status, resp, "photo")

    def find_category_id(self, slug: str) -> int | str | None:
        status, data = self._request(
            "GET",
            "/api/categories",
            query={"where[slug][equals]": slug, "depth": "0", "limit": "1"},
        )
        docs = data.get("docs") or [] if status == 200 else []
        return docs[0].get("id") if docs and isinstance(docs[0], dict) else None
