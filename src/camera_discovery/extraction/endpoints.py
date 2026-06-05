from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from camera_discovery.extraction.media import _dedupe_strings
from camera_discovery.harvest.media_filter import canonical_media_url

ENDPOINT_HINT_RE = re.compile(
    r"(?:\.json(?:[?#]|$)|\.geojson(?:[?#]|$)|/api/|/feed|/feeds|/data/|/layers?|/query|MapServer|FeatureServer|collections|items|wfs|service=wfs|f=geojson|f=json|camera|cameras)",
    re.I,
)
_QUOTED_ENDPOINT_RE = re.compile(
    r"[\"']([^\"']*(?:\.json(?:[?#]|$)|\.geojson(?:[?#]|$)|/api/|/feed|/feeds|/data/|/layers?|/query|MapServer|FeatureServer|collections|items|wfs|service=wfs|f=geojson|f=json)[^\"']*)[\"']",
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
    r"\b(?:endpoint|feed|api|geojson|jsonUrl|dataUrl|layerUrl|serviceUrl|queryUrl|url)\w*\s*[:=]\s*[\"']([^\"']+)[\"']",
    re.I,
)
_ARCGIS_SERVICE_RE = re.compile(r"/(?:MapServer|FeatureServer)/?$", re.I)
_ARCGIS_LAYER_RE = re.compile(r"/(?:MapServer|FeatureServer)/(\d+)/?$", re.I)
_ARCGIS_QUERY_RE = re.compile(r"/(?:MapServer|FeatureServer)/(\d+)/query$", re.I)
_OGC_COLLECTIONS_RE = re.compile(r"/collections/?$", re.I)
_OGC_COLLECTION_RE = re.compile(r"/collections/[^/]+/?$", re.I)
_JS_BUNDLE_RE = re.compile(r"\.m?js(?:[?#]|$)", re.I)


@dataclass(frozen=True)
class StructuredEndpointRef:
    """A bounded public structured-endpoint fetch target.

    ``reason`` and ``parent_url`` are diagnostics only.  The URL remains the only
    fetch target and must still pass caller source-policy checks before use.
    """

    url: str
    endpoint_type: str
    reason: str
    parent_url: str | None = None

    def to_log_record(self, *, page_url: str | None = None) -> dict[str, Any]:
        record = asdict(self)
        if page_url is not None:
            record["page_url"] = page_url
        return record


class StructuredEndpointResponseCache:
    """Cache successful structured-endpoint responses for one extraction scope.

    Callers deliberately control the cache lifetime. Normal discovery and harvest
    create one cache per source-page extraction so metadata expansion and record
    extraction can reuse the exact same successful response without introducing
    cross-page staleness or unbounded run-level memory. Failed requests and HTTP
    error responses are not cached, preserving the existing later retry chance.
    """

    def __init__(self) -> None:
        self._responses: dict[str, Any] = {}

    def get_or_fetch(self, url: str, fetch: Callable[[str], Any]) -> tuple[Any, bool]:
        key = _response_cache_key(url)
        cached = self._responses.get(key)
        if cached is not None:
            return cached, True
        response = fetch(url)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and status_code < 400:
            self._responses[key] = response
        return response, False

    def __len__(self) -> int:
        return len(self._responses)


def extract_endpoint_urls_from_text(text: str, base_url: str, *, max_bytes: int = 2_000_000) -> list[str]:
    """Extract public JSON/API/ArcGIS/GeoJSON endpoint URLs from page text.

    This compatibility wrapper returns URL strings only.  New call sites should
    prefer :func:`extract_structured_endpoint_refs_from_text` when they need
    endpoint type and discovery-reason diagnostics.
    """
    return [ref.url for ref in extract_structured_endpoint_refs_from_text(text, base_url, max_bytes=max_bytes)]


def extract_structured_endpoint_refs_from_text(text: str, base_url: str, *, max_bytes: int = 2_000_000) -> list[StructuredEndpointRef]:
    if not text:
        return []
    window = text[:max_bytes]
    refs: list[StructuredEndpointRef] = []
    for pattern, reason in (
        (_QUOTED_ENDPOINT_RE, "quoted_endpoint_literal"),
        (_DIRECT_CALL_RE, "xhr_or_fetch_call"),
        (_XHR_OPEN_RE, "xhr_open_call"),
        (_AJAX_URL_RE, "ajax_url_property"),
        (_JS_ASSIGNMENT_RE, "javascript_endpoint_assignment"),
    ):
        for match in pattern.finditer(window):
            raw = _clean_js_url(match.group(1))
            if not raw or not ENDPOINT_HINT_RE.search(raw):
                continue
            absolute = canonical_media_url(urljoin(base_url, raw))
            if _is_http_url(absolute):
                refs.append(StructuredEndpointRef(absolute, _endpoint_type_for_url(absolute), reason, base_url))
    return _dedupe_endpoint_refs(refs)


def linked_script_urls_from_html(html: str, base_url: str, *, max_scripts: int = 8) -> list[str]:
    """Return explicit public JavaScript bundle URLs referenced by a page.

    The caller is responsible for source-policy checks and fetching.  This does
    not guess script paths; it only follows explicit ``script[src]`` references.
    """
    urls: list[str] = []
    for match in re.finditer(r"<script\b[^>]*\bsrc\s*=\s*([\"'])(.*?)\1", html or "", re.I | re.S):
        absolute = canonical_media_url(urljoin(base_url, _clean_js_url(match.group(2))))
        if _is_http_url(absolute) and _JS_BUNDLE_RE.search(absolute):
            urls.append(absolute)
    return _dedupe_strings(urls)[:max_scripts]


def expand_structured_endpoint_refs_from_metadata(
    refs: Iterable[StructuredEndpointRef | str],
    *,
    fetch_json: Callable[[str], Any | None] | None = None,
    is_blocked: Callable[[str], bool] | None = None,
    max_endpoints: int = 100,
) -> list[StructuredEndpointRef]:
    """Expand explicitly discovered endpoints using public service metadata.

    ArcGIS service roots are expanded only by reading their advertised
    ``layers``/``tables`` metadata.  The function intentionally does not guess
    layer IDs or paths.  OGC API Features links/collections are followed only
    when advertised by a fetched JSON document.
    """
    out: list[StructuredEndpointRef] = []
    queue: list[StructuredEndpointRef] = []
    for item in refs:
        ref = item if isinstance(item, StructuredEndpointRef) else StructuredEndpointRef(str(item), _endpoint_type_for_url(str(item)), "explicit_endpoint")
        if not _is_http_url(ref.url) or (is_blocked and is_blocked(ref.url)):
            continue
        queue.append(_normalize_endpoint_ref(ref))
    seen: set[str] = set()
    while queue and len(out) < max_endpoints:
        ref = queue.pop(0)
        key = _canonical_endpoint_key(ref.url)
        if key in seen or (is_blocked and is_blocked(ref.url)):
            continue
        seen.add(key)
        out.append(ref)
        if fetch_json is None:
            continue
        for child in _metadata_children(ref, fetch_json):
            if len(out) + len(queue) >= max_endpoints:
                break
            if is_blocked and is_blocked(child.url):
                continue
            child_key = _canonical_endpoint_key(child.url)
            if child_key not in seen:
                queue.append(child)
    return out


def _metadata_children(ref: StructuredEndpointRef, fetch_json: Callable[[str], Any | None]) -> list[StructuredEndpointRef]:
    parsed = urlparse(ref.url)
    path = parsed.path.rstrip("/")
    if _ARCGIS_SERVICE_RE.search(path):
        metadata_url = _with_query(parsed._replace(query="").geturl(), {"f": "pjson"})
        metadata = fetch_json(metadata_url)
        return _arcgis_layer_query_refs(ref.url, metadata)
    if _OGC_COLLECTIONS_RE.search(path) or _endpoint_type_for_url(ref.url) == "ogc_api_features":
        metadata = fetch_json(_with_query(ref.url, {"f": "json"}) if not parsed.query else ref.url)
        return _ogc_feature_refs(ref.url, metadata)
    data = None
    if ref.endpoint_type in {"json", "geojson", "api", "arcgis_metadata"}:
        data = fetch_json(ref.url)
    return _advertised_link_refs(ref.url, data)


def _arcgis_layer_query_refs(service_url: str, metadata: Any | None) -> list[StructuredEndpointRef]:
    if not isinstance(metadata, dict):
        return []
    base = service_url.split("?", 1)[0].rstrip("/")
    refs: list[StructuredEndpointRef] = []
    for group_name in ("layers", "tables"):
        entries = metadata.get(group_name)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            layer_id = entry.get("id")
            if isinstance(layer_id, bool):
                continue
            try:
                layer_int = int(layer_id)
            except (TypeError, ValueError):
                continue
            query_url = f"{base}/{layer_int}/query?where=1%3D1&outFields=*&returnGeometry=true&f=json"
            refs.append(StructuredEndpointRef(query_url, "arcgis_query", f"advertised_arcgis_{group_name}_metadata", service_url))
    return _dedupe_endpoint_refs(refs)


def _ogc_feature_refs(parent_url: str, metadata: Any | None) -> list[StructuredEndpointRef]:
    refs: list[StructuredEndpointRef] = []
    if not isinstance(metadata, dict):
        return refs
    collections = metadata.get("collections")
    if isinstance(collections, list):
        for item in collections:
            if not isinstance(item, dict):
                continue
            links = item.get("links")
            if isinstance(links, list):
                refs.extend(_refs_from_link_objects(links, parent_url, "advertised_ogc_collection_link"))
            collection_id = item.get("id")
            if isinstance(collection_id, str) and collection_id.strip():
                refs.append(StructuredEndpointRef(urljoin(parent_url.rstrip("/") + "/", f"{collection_id}/items?f=json"), "ogc_items", "advertised_ogc_collection_id", parent_url))
    refs.extend(_advertised_link_refs(parent_url, metadata))
    return _dedupe_endpoint_refs(refs)


def _advertised_link_refs(parent_url: str, data: Any | None) -> list[StructuredEndpointRef]:
    if not isinstance(data, dict):
        return []
    refs: list[StructuredEndpointRef] = []
    links = data.get("links")
    if isinstance(links, list):
        refs.extend(_refs_from_link_objects(links, parent_url, "advertised_structured_link"))
    for key in ("url", "href", "dataUrl", "geojson", "features", "items"):
        value = data.get(key)
        if isinstance(value, str) and ENDPOINT_HINT_RE.search(value):
            absolute = canonical_media_url(urljoin(parent_url, value))
            if _is_http_url(absolute):
                refs.append(StructuredEndpointRef(absolute, _endpoint_type_for_url(absolute), f"advertised_{key}", parent_url))
    return _dedupe_endpoint_refs(refs)


def _refs_from_link_objects(links: list[Any], parent_url: str, reason: str) -> list[StructuredEndpointRef]:
    refs: list[StructuredEndpointRef] = []
    for link in links:
        if not isinstance(link, dict):
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href.strip():
            continue
        link_type = str(link.get("type") or "").casefold()
        rel = str(link.get("rel") or "").casefold()
        absolute = canonical_media_url(urljoin(parent_url, href))
        if not _is_http_url(absolute):
            continue
        if ENDPOINT_HINT_RE.search(absolute) or any(token in link_type for token in ("json", "geo+json", "geojson")) or rel in {"items", "data", "collection"}:
            refs.append(StructuredEndpointRef(absolute, _endpoint_type_for_url(absolute), reason, parent_url))
    return refs


def _normalize_endpoint_ref(ref: StructuredEndpointRef) -> StructuredEndpointRef:
    parsed = urlparse(ref.url)
    path = parsed.path.rstrip("/")
    if _ARCGIS_LAYER_RE.search(path):
        query_url = parsed._replace(query="where=1%3D1&outFields=*&returnGeometry=true&f=json").geturl().rstrip("/")
        return StructuredEndpointRef(query_url, "arcgis_query", "arcgis_layer_query_from_explicit_layer", ref.url)
    if _ARCGIS_QUERY_RE.search(path) and not parsed.query:
        return StructuredEndpointRef(parsed._replace(query="where=1%3D1&outFields=*&returnGeometry=true&f=json").geturl(), "arcgis_query", "arcgis_query_default_parameters", ref.parent_url)
    if _OGC_COLLECTION_RE.search(path):
        return StructuredEndpointRef(parsed._replace(path=parsed.path.rstrip("/") + "/items", query="f=json").geturl(), "ogc_items", "ogc_items_from_explicit_collection", ref.url)
    return StructuredEndpointRef(ref.url, ref.endpoint_type or _endpoint_type_for_url(ref.url), ref.reason, ref.parent_url)


def _with_query(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        query.setdefault(key, [value])
    return parsed._replace(query=urlencode(query, doseq=True)).geturl()


def _response_cache_key(url: str) -> str:
    """Return an exact canonical fetch key without folding path/query case."""
    return canonical_media_url(url).split("#", 1)[0]


def _canonical_endpoint_key(url: str) -> str:
    return canonical_media_url(url).split("#", 1)[0].casefold()


def _dedupe_endpoint_refs(refs: Iterable[StructuredEndpointRef]) -> list[StructuredEndpointRef]:
    seen: set[str] = set()
    out: list[StructuredEndpointRef] = []
    for ref in refs:
        key = _canonical_endpoint_key(ref.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out


def _endpoint_type_for_url(url: str) -> str:
    lower = url.casefold()
    path = urlparse(url).path.rstrip("/").casefold()
    if "/featureserver" in path or "/mapserver" in path:
        if "/query" in path:
            return "arcgis_query"
        if re.search(r"/(?:featureserver|mapserver)/\d+$", path):
            return "arcgis_layer"
        return "arcgis_service"
    if "f=geojson" in lower or path.endswith(".geojson"):
        return "geojson"
    if "service=wfs" in lower:
        return "wfs"
    if "/collections" in path or "/items" in path:
        return "ogc_api_features"
    if path.endswith(".json") or "f=json" in lower:
        return "json"
    if "/api/" in path:
        return "api"
    return "structured_endpoint"


def _clean_js_url(value: str) -> str:
    raw = str(value or "").strip().strip("\"\'`),;}]")
    raw = raw.replace(r"\/", "/").replace(r"\u002F", "/").replace(r"\u002f", "/")
    return raw


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
