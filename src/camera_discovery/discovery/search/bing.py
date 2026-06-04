from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from camera_discovery.extraction.html import _html_soup

_BING_BLOCKED_HOSTS = {"bing.com", "www.bing.com", "microsoft.com", "www.microsoft.com", "go.microsoft.com"}


def clean_bing_result_url(href: str) -> str:
    """Return the external destination represented by a Bing result link."""
    raw = str(href or "").strip().strip('"\'')
    if not raw or raw.startswith(("#", "javascript:", "mailto:")):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = "https://www.bing.com" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        return ""
    qs = parse_qs(parsed.query)
    for key in ("u", "url", "r"):
        if qs.get(key):
            candidate = unquote(qs[key][0]).strip()
            if candidate.startswith(("http://", "https://")):
                return candidate
    host = parsed.netloc.casefold()
    if host in _BING_BLOCKED_HOSTS:
        return ""
    return raw


def parse_bing_results(html: str, *, query: str = "", max_results: int = 50) -> list[dict[str, Any]]:
    """Parse Bing HTML results into normalized search rows."""
    if max_results <= 0 or not html:
        return []
    soup = _html_soup(html)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(href: str, title: str = "", snippet: str = "") -> None:
        if len(rows) >= max_results:
            return
        url = clean_bing_result_url(href)
        if not url:
            return
        key = url.split("#", 1)[0]
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "query": query,
                "title": title.strip() or key,
                "url": key,
                "snippet": snippet.strip(),
                "source_provider": "blind:bing",
                "source_name": "Bing",
                "source_kind": "search_result",
                "search_engine": "bing",
            }
        )

    for li in soup.select("li.b_algo"):
        link = li.select_one("h2 a[href]") or li.select_one("a[href]")
        if link is None:
            continue
        snippet = ""
        paragraph = li.select_one("p")
        if paragraph is not None:
            snippet = paragraph.get_text(" ", strip=True)[:500]
        add(link.get("href") or "", link.get_text(" ", strip=True), snippet)
        if len(rows) >= max_results:
            return rows

    for anchor in soup.select("h2 a[href], h3 a[href], a[href]"):
        add(anchor.get("href") or "", anchor.get_text(" ", strip=True), "")
        if len(rows) >= max_results:
            return rows

    for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.I | re.S):
        title = re.sub(r"<[^>]+>", " ", match.group(2))
        add(match.group(1), " ".join(title.split()), "")
        if len(rows) >= max_results:
            return rows
    return rows
