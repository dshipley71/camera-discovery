from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "client_secret",
    "code",
    "key",
    "password",
    "secret",
    "session",
    "sig",
    "signature",
    "token",
}

ALLOWLISTED_HEADERS = {
    "content-type",
    "content-length",
    "server",
    "x-powered-by",
    "www-authenticate",
    "last-modified",
    "etag",
    "cache-control",
    "access-control-allow-origin",
}

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", flags=re.IGNORECASE | re.DOTALL)


def redact_sensitive_url(url: str | None) -> str | None:
    """Return a URL with credentials and sensitive query values redacted."""
    if not url:
        return url
    try:
        parts = urlsplit(str(url))
    except Exception:
        return str(url)
    netloc = parts.netloc
    if "@" in netloc:
        host = netloc.rsplit("@", 1)[-1]
        netloc = f"***:***@{host}"
    redacted_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.casefold() in SENSITIVE_QUERY_KEYS or any(token in key.casefold() for token in ("token", "secret", "password", "signature")):
            redacted_query.append((key, "***"))
        else:
            redacted_query.append((key, value))
    return urlunsplit((parts.scheme, netloc, parts.path, urlencode(redacted_query, doseq=True), parts.fragment))


def title_from_html(text: str | None) -> str | None:
    if not text:
        return None
    match = _TITLE_RE.search(text[:200000])
    if not match:
        return None
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return title[:300] or None


def allowlisted_headers(headers: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in dict(headers or {}).items():
        lower = str(key).casefold()
        if lower not in ALLOWLISTED_HEADERS:
            continue
        if lower == "www-authenticate":
            out[lower] = "present"
        else:
            out[lower] = str(value)[:500]
    return out


def _auth_realm(headers: Any) -> str | None:
    value = ""
    try:
        value = str(dict(headers or {}).get("www-authenticate") or dict(headers or {}).get("WWW-Authenticate") or "")
    except Exception:
        value = ""
    if not value:
        return None
    match = re.search(r'realm="?([^",]+)', value, flags=re.IGNORECASE)
    return match.group(1)[:200] if match else None


def http_metadata_from_response(response: Any, *, text: str | None = None, started_at: float | None = None, error: str | None = None) -> dict[str, Any]:
    """Capture passive HTTP metadata from a response already fetched by the pipeline."""
    if response is None:
        return {"fetch_error": error} if error else {}
    headers = getattr(response, "headers", {}) or {}
    try:
        final_url = str(getattr(response, "url", "") or "")
    except Exception:
        final_url = ""
    try:
        history = list(getattr(response, "history", []) or [])
    except Exception:
        history = []
    status = getattr(response, "status_code", None)
    content_type = str(headers.get("content-type") or headers.get("Content-Type") or "")[:500]
    content_length = headers.get("content-length") or headers.get("Content-Length")
    try:
        content_length_value = int(content_length) if content_length not in (None, "") else None
    except (TypeError, ValueError):
        content_length_value = None
    response_ms = None
    if started_at is not None:
        response_ms = max(0, int((time.monotonic() - started_at) * 1000))
    return {
        "http_status": status,
        "final_url": redact_sensitive_url(final_url),
        "redirect_count": len(history),
        "content_type": content_type or None,
        "content_length": content_length_value,
        "server": str(headers.get("server") or headers.get("Server") or "")[:200] or None,
        "www_authenticate_present": bool(headers.get("www-authenticate") or headers.get("WWW-Authenticate")),
        "auth_realm": _auth_realm(headers),
        "title": title_from_html(text) if text else None,
        "response_ms": response_ms,
        "fetch_error": error,
        "headers": allowlisted_headers(headers),
    }
