from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

from camera_discovery.extraction.html import _html_soup

_DDG_HOSTS = {"duckduckgo.com", "www.duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com"}
_RESULT_SELECTORS = [
    "a.result__a",
    "a[data-testid=\"result-title-a\"]",
    "a[data-testid=\"result-title\"]",
    "a[data-testid=\"result-extras-url-link\"]",
    ".result a[href]",
    ".web-result a[href]",
    ".results a[href]",
    "article a[href]",
    "h2 a[href]",
    "h3 a[href]",
    "a[href*=\"uddg=\"]",
]
_DDG_TRACKING_PATHS = {"/l/", "/y.js"}


def clean_ddg_result_url(href: str) -> str:
    """Return the external URL represented by a DuckDuckGo result link.

    DuckDuckGo has used several result-page shapes over time: classic
    ``/l/?uddg=...`` redirects, absolute result links with a ``uddg`` query
    parameter, and direct external links.  This helper deliberately rejects
    internal DuckDuckGo navigation/assets so a markup change degrades to fewer
    rows rather than noisy internal rows.
    """

    if not href:
        return ""
    raw = href.strip().strip('\"\'')
    if not raw or raw.startswith(("#", "javascript:", "mailto:")):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = "https://duckduckgo.com" + raw

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return ""

    qs = parse_qs(parsed.query)
    if qs.get("uddg"):
        return unquote(qs["uddg"][0]).strip()

    host = parsed.netloc.casefold()
    if host in _DDG_HOSTS:
        return ""
    return raw


def parse_ddg_result_rows(
    query: str,
    html: str,
    *,
    max_results: int,
    include_source_kind: bool = False,
) -> list[dict[str, str]]:
    """Parse DuckDuckGo HTML/lite result pages into blind source rows.

    The parser intentionally supports multiple selector families instead of the
    historical single ``a.result__a`` selector.  That keeps blind row discovery
    resilient when DDG changes between classic, lite, and modern result markup.
    """

    if max_results <= 0 or not html:
        return []

    soup = _html_soup(html)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(href: str, title: str = "", snippet: str = "") -> None:
        if len(rows) >= max_results:
            return
        url = clean_ddg_result_url(href)
        if not url:
            return
        key = url.split("#", 1)[0]
        if key in seen:
            return
        seen.add(key)
        row = {
            "query": query,
            "title": title.strip() or key,
            "url": key,
            "snippet": snippet.strip(),
            "source_provider": "blind",
            "source_name": "DuckDuckGo",
        }
        if include_source_kind:
            row["source_kind"] = "search_result"
        rows.append(row)

    for selector in _RESULT_SELECTORS:
        for anchor in soup.select(selector):
            href = anchor.get("href") or ""
            title = anchor.get_text(" ", strip=True)
            snippet = ""
            parent = anchor.find_parent(class_=re.compile(r"(^|[-_ ])result($|[-_ ])", re.I))
            if parent is not None:
                snippet = parent.get_text(" ", strip=True)[:500]
            add(href, title, snippet)
            if len(rows) >= max_results:
                return rows

    # Fallback for stripped/lite pages or cached samples where only redirect
    # URLs remain in text attributes.  Keep this as a last resort so selector
    # based title extraction wins when available.
    for match in re.finditer(r"uddg=([^&\"'<>\s]+)", html):
        add("https://duckduckgo.com/l/?uddg=" + match.group(1), "", "")
        if len(rows) >= max_results:
            return rows

    return rows
