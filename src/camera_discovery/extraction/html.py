from __future__ import annotations

import warnings
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, FeatureNotFound, XMLParsedAsHTMLWarning

from camera_discovery.extraction.media import _dedupe_media_urls, _looks_like_hls, _looks_like_image, _looks_like_rtsp
from camera_discovery.harvest.media_filter import canonical_media_url


def _html_soup(html: str) -> BeautifulSoup:
    """Parse HTML/XML-ish text without surfacing BeautifulSoup XML warnings.

    Some public feeds return XML/RSS/KML-ish content from URLs that the discovery
    crawler treats like pages. BeautifulSoup's HTML parser emits
    XMLParsedAsHTMLWarning for those responses; using the XML parser when the
    document clearly looks XML-like avoids noisy captured output while preserving
    real parsing.
    """
    prefix = (html or "").lstrip()[:200].lower()
    parser = "xml" if (prefix.startswith("<?xml") or prefix.startswith("<rss") or prefix.startswith("<feed") or prefix.startswith("<kml")) else "html.parser"
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
        try:
            return BeautifulSoup(html, parser)
        except FeatureNotFound:
            # Some minimal CI/runtime environments have BeautifulSoup installed
            # without an XML parser such as lxml. Fall back to the built-in HTML
            # parser while preserving the warning-suppression contract.
            return BeautifulSoup(html, "html.parser")

def _media_urls_from_html_tag(tag: Any, base_url: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for attr in ("src", "data-src", "data-original", "data-image", "data-url", "poster"):
        value = tag.get(attr) if hasattr(tag, "get") else None
        if isinstance(value, str) and value.strip():
            urls.extend(_media_urls_from_attribute(value, base_url))
    srcset = tag.get("srcset") if hasattr(tag, "get") else None
    if isinstance(srcset, str):
        for part in srcset.split(","):
            candidate = part.strip().split(" ", 1)[0]
            urls.extend(_media_urls_from_attribute(candidate, base_url))
    return _dedupe_media_urls(urls)

def _media_urls_from_attribute(value: str, base_url: str) -> list[tuple[str, str]]:
    absolute = canonical_media_url(urljoin(base_url, value.strip()))
    if _looks_like_hls(absolute):
        return [(absolute, "hls")]
    if _looks_like_rtsp(absolute):
        return [(absolute, "rtsp")]
    if _looks_like_image(absolute):
        return [(absolute, "image_snapshot")]
    return []

def _metadata_from_html_tag(tag: Any) -> dict[str, Any]:
    if tag is None or not hasattr(tag, "attrs"):
        return {}
    out: dict[str, Any] = {}
    for raw_key, raw_value in dict(tag.attrs).items():
        key = str(raw_key).replace("-", "_").casefold()
        if isinstance(raw_value, list):
            value: Any = " ".join(str(part) for part in raw_value)
        else:
            value = raw_value
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
    return out

def _nearby_text(tag: Any) -> str | None:
    parent = getattr(tag, "parent", None)
    if parent is None or not hasattr(parent, "get_text"):
        return None
    text = " ".join(parent.get_text(" ", strip=True).split())
    if not text or len(text) > 180:
        return None
    return text

def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()[:300]
    return None
