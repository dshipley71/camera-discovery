from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

from camera_discovery.core.models import TargetContext
from camera_discovery.sources import SourceEntry, SourcePolicy
from camera_discovery.extraction.media import _dedupe_strings, _looks_like_hls, _looks_like_rtsp


class DirectorySourceProvider:
    """Expose user-approved directory sources from SOURCES.md as discovery inputs.

    `page`, `feed`, and `direct_hls` entries are used directly. `site` entries are
    expanded into target-aware candidate pages before the root URL is fetched. This
    keeps the simplified architecture intact while making directory mode useful for
    camera-directory home pages such as OpenCCTV: the source registry supplies the
    approved site, and this provider derives generic camera/location paths from the
    target context without adding source-specific crawling logic.
    """

    def __init__(self, policy: SourcePolicy):
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for entry in self.policy.enabled_allowed_sources():
            if self.policy.is_blocked(entry.url):
                continue
            if entry.source_type == "site":
                rows.extend(_target_aware_site_rows(entry, target))
            rows.append(_row_from_source_entry(entry, target))
        return _dedupe_rows(rows)

class DirectUrlSourceProvider:
    """Expose command-line seed URLs as discovery inputs while respecting global block rules."""

    def __init__(self, urls: list[str], policy: SourcePolicy):
        self.urls = urls
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for url in self.urls:
            if self.policy.is_blocked(url):
                continue
            entry = SourceEntry(name=url, url=url, source_type="direct_hls" if _looks_like_hls(url) else "page")
            rows.append(_row_from_source_entry(entry, target, provider="direct"))
        return rows

def _target_aware_site_rows(entry: SourceEntry, target: TargetContext) -> list[dict[str, str]]:
    """Generate generic target-aware pages for approved camera-directory sites.

    This is intentionally not a source-specific parser. It derives common public
    camera-directory URL shapes from the resolved target and camera intent, then
    lets the normal fetch/extract pipeline decide which pages actually exist.
    """
    base = entry.url.rstrip("/") + "/"
    region_slugs = _target_region_slugs(target)
    country_slugs = _target_country_slugs(target)
    category_slugs = _camera_category_slugs(target)
    urls: list[str] = []
    for country in country_slugs:
        for region in region_slugs:
            urls.extend(
                [
                    urljoin(base, f"cameras/{country}/{region}"),
                    urljoin(base, f"livetraffic/{country}/{region}"),
                ]
            )
            for category in category_slugs:
                urls.append(urljoin(base, f"cameras/{country}/{region}/category/{category}"))
                for page in range(1, 6):
                    urls.append(urljoin(base, f"cameras/{country}/{region}/category/{category}?page={page}"))
    rows = []
    for url in _dedupe_strings(urls):
        if not url.startswith("http"):
            continue
        row = _row_from_source_entry(entry, target, provider="directory")
        row["url"] = url
        row["source_type"] = "site_target_page"
        rows.append(row)
    return rows

def _target_region_slugs(target: TargetContext) -> list[str]:
    values = [target.admin_region, target.canonical_target, target.target_label, target.intent.place_name]
    # For state/county/region targets, canonical labels often include country
    # punctuation. Keep only useful place fragments and dedupe after slugging.
    slugs: list[str] = []
    for value in values:
        if not value:
            continue
        fragment = str(value).split(",", 1)[0]
        slug = _slugify(fragment)
        if slug and slug not in {"traffic", "traffic-cameras", "cameras", "live-cameras"}:
            slugs.append(slug)
    return _dedupe_strings(slugs) or ["all"]

def _target_country_slugs(target: TargetContext) -> list[str]:
    values = [target.country]
    # Include country fragments from canonical strings such as
    # "California, United States" without assuming a specific test location.
    if target.canonical_target and "," in target.canonical_target:
        values.append(target.canonical_target.rsplit(",", 1)[-1].strip())
    slugs = [_slugify(v) for v in values if v]
    return _dedupe_strings([s for s in slugs if s]) or ["world"]

def _camera_category_slugs(target: TargetContext) -> list[str]:
    intent = (target.intent.camera_type_intent or "camera").casefold().replace("_", " ")
    categories = [intent, "traffic" if "traffic" in intent else "camera"]
    return _dedupe_strings([_slugify(c) for c in categories if c])

def _slugify(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).casefold().strip()
    text = re.sub(r"&", " and ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def _dedupe_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in rows:
        url = (row.get("url") or "").split("#", 1)[0]
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({**row, "url": url})
    return out

def _row_from_source_entry(entry: SourceEntry, target: TargetContext, provider: str = "directory") -> dict[str, str]:
    return {
        "query": f"{provider}:{target.target_id}",
        "title": entry.name,
        "url": entry.url,
        "snippet": entry.notes or "",
        "source_provider": provider,
        "source_kind": entry.source_type,
        "source_name": entry.name,
        "source_scope_hint": entry.scope_hint or "",
        "source_notes": entry.notes or "",
    }

def _url_query_mapping(url: str) -> dict[str, Any]:
    if not url:
        return {}
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    return {key: values[0] for key, values in qs.items() if values}
