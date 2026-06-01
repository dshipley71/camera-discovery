from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}
_PRIVATE_SUFFIXES = (".localhost", ".local")


def is_private_or_local_media_url(url: str | None) -> bool:
    """Return True for media URLs that should not be probed or exported.

    The check is intentionally deterministic and non-networked: it rejects IP
    literals in private/reserved/local ranges and obvious localhost-style names,
    but it does not resolve DNS names.
    """

    if not url:
        return False
    try:
        split = urlsplit(url)
    except Exception:
        return True
    host = (split.hostname or "").strip().casefold().rstrip(".")
    if not host:
        return True
    if host in _PRIVATE_HOSTNAMES or host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def redact_url_userinfo(url: str | None) -> str:
    """Redact username/password from a URL for diagnostics and metadata."""

    if not url:
        return ""
    try:
        split = urlsplit(url)
    except Exception:
        return str(url)
    if "@" not in split.netloc:
        return url
    host = split.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    port = f":{split.port}" if split.port else ""
    return urlunsplit((split.scheme, f"***:***@{host}{port}", split.path, split.query, split.fragment))
