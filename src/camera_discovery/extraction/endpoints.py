from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from camera_discovery.extraction.media import _dedupe_strings
from camera_discovery.harvest.media_filter import canonical_media_url

ENDPOINT_HINT_RE = re.compile(
    r"(?:\.json(?:[?#]|$)|\.geojson(?:[?#]|$)|/api/|/feed|/feeds|/data/|/layers?|/query|MapServer|FeatureServer|f=geojson|f=json|camera|cameras)",
    re.I,
)
_QUOTED_ENDPOINT_RE = re.compile(
    r"[\"']([^\"']*(?:\.json(?:[?#]|$)|\.geojson(?:[?#]|$)|/api/|/feed|/feeds|/data/|/layers?|/query|MapServer|FeatureServer|f=geojson|f=json)[^\"']*)[\"']",
    re.I,
)
_DIRECT_CALL_RE = re.compile(
    r"(?:fetch|axios\.(?:get|post|request)|\$\.(?:getJSON|get|post))\s*\(\s*[\"']([^\"']+)[\"']",
    re.I,
)
_XHR_OPEN_RE = re.compile(
    r"\.open\s*\(\s*[\"'](?:GET|POST)[\"']\s*,\s*[\"']([^\"']+)[\"']",
    re.I,
)
_AJAX_URL_RE = re.compile(r"\burl\s*:\s*[\"']([^\"']+)[\"']", re.I)
_JS_ASSIGNMENT_RE = re.compile(
    r"\b(?:endpoint|feed|api|geojson|jsonUrl|dataUrl|layerUrl|serviceUrl|queryUrl)\w*\s*=\s*[\"']([^\"']+)[\"']",
    re.I,
)


def extract_endpoint_urls_from_text(text: str, base_url: str, *, max_bytes: int = 2_000_000) -> list[str]:
    """Extract public JSON/API/ArcGIS/GeoJSON endpoint URLs from page text.

    This covers quoted endpoint literals plus common XHR/fetch forms such as
    fetch(...), $.getJSON(...), axios.get(...), xhr.open("GET", ...), and
    jQuery ajax({url: ...}). Returned URLs are absolute HTTP(S) URLs only.
    """
    if not text:
        return []
    window = text[:max_bytes]
    urls: list[str] = []
    for pattern in (_QUOTED_ENDPOINT_RE, _DIRECT_CALL_RE, _XHR_OPEN_RE, _AJAX_URL_RE, _JS_ASSIGNMENT_RE):
        for match in pattern.finditer(window):
            raw = _clean_js_url(match.group(1))
            if not raw or not ENDPOINT_HINT_RE.search(raw):
                continue
            absolute = canonical_media_url(urljoin(base_url, raw))
            if _is_http_url(absolute):
                urls.append(absolute)
    return _dedupe_strings(urls)


def _clean_js_url(value: str) -> str:
    raw = str(value or "").strip().strip('"\'`),;}]')
    raw = raw.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")
    return raw


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
