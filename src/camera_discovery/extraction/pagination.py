from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from camera_discovery.core.models import TargetContext
from camera_discovery.discovery.source_rows import _camera_category_slugs, _target_region_slugs
from camera_discovery.extraction.media import _dedupe_strings


def _pagination_rows(row: dict[str, str], max_pages: int) -> list[dict[str, str]]:
    url = row.get("url") or ""
    if max_pages <= 1 or not _looks_like_paginated_directory_url(url):
        return []
    rows: list[dict[str, str]] = []
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for page in range(2, max_pages + 1):
        new_query = {key: values[:] for key, values in query.items()}
        new_query["page"] = [str(page)]
        qs = urlencode(new_query, doseq=True)
        page_url = parsed._replace(query=qs).geturl()
        new_row = dict(row)
        new_row["url"] = page_url
        new_row["source_kind"] = row.get("source_kind") or "paginated_page"
        new_row["discovery_note"] = f"pagination_page_{page}"
        rows.append(new_row)
    return rows

def _looks_like_pagination_url(url: str) -> bool:
    lower = url.casefold()
    return any(token in lower for token in ("page=", "/page/", "offset=", "start=", "next", "camera", "webcam", "cctv"))

def _looks_like_paginated_directory_url(url: str) -> bool:
    lower = url.casefold()
    if not lower.startswith("http"):
        return False
    return any(token in lower for token in ("/camera", "/cameras", "/traffic", "/category/", "/livet", "webcam", "cctv"))

def _expand_structured_endpoint_urls(urls: list[str]) -> list[str]:
    expanded: list[str] = []
    for url in urls:
        expanded.append(url)
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if re.search(r"/(?:MapServer|FeatureServer)(?:/\d+)?$", path, re.I):
            base = parsed._replace(query="", fragment="").geturl().rstrip("/")
            if re.search(r"/(?:MapServer|FeatureServer)$", path, re.I):
                # Try a small generic range of layer IDs. Non-existing layers are harmless and logged.
                for layer in range(0, 8):
                    expanded.append(f"{base}/{layer}/query?where=1%3D1&outFields=*&returnGeometry=true&f=json")
            else:
                expanded.append(f"{base}/query?where=1%3D1&outFields=*&returnGeometry=true&f=json")
        elif "/query" in path.casefold() and not parsed.query:
            expanded.append(parsed._replace(query="where=1%3D1&outFields=*&returnGeometry=true&f=json").geturl())
    return _dedupe_strings(expanded)

def _asset_host_discovery_urls(host: str, target: TargetContext) -> list[str]:
    scheme_host = f"https://{host}"
    slugs = _target_region_slugs(target)[:3]
    category_slugs = _camera_category_slugs(target)[:3]
    urls = [scheme_host, f"{scheme_host}/cameras", f"{scheme_host}/camera", f"{scheme_host}/traffic", f"{scheme_host}/cctv"]
    for slug in slugs:
        urls.extend([f"{scheme_host}/{slug}", f"{scheme_host}/cameras/{slug}", f"{scheme_host}/traffic/{slug}"])
        for category in category_slugs:
            urls.append(f"{scheme_host}/cameras/{slug}/category/{category}")
    return _dedupe_strings(urls)
