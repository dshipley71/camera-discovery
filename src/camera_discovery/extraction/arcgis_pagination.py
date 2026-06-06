from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from typing import Any, Literal
from urllib.parse import parse_qs, urlencode, urlparse

from camera_discovery.extraction.endpoints import StructuredEndpointResponseCache

ArcGisPaginationStrategy = Literal["auto", "offset", "object_ids", "single_page"]


@dataclass(frozen=True)
class ArcGisPaginationConfig:
    strategy: ArcGisPaginationStrategy = "auto"
    page_size: int = 1000
    object_id_batch_size: int = 500
    max_pages_per_layer: int = 100
    max_records_per_layer: int = 0

    def __post_init__(self) -> None:
        allowed = {"auto", "offset", "object_ids", "single_page"}
        if self.strategy not in allowed:
            raise ValueError(f"Invalid ArcGIS pagination strategy {self.strategy!r}; expected one of: {', '.join(sorted(allowed))}")
        object.__setattr__(self, "page_size", max(1, int(self.page_size or 1000)))
        object.__setattr__(self, "object_id_batch_size", max(1, int(self.object_id_batch_size or 500)))
        object.__setattr__(self, "max_pages_per_layer", max(1, int(self.max_pages_per_layer or 100)))
        object.__setattr__(self, "max_records_per_layer", max(0, int(self.max_records_per_layer or 0)))


@dataclass
class ArcGisPaginationResult:
    features: list[dict[str, Any]] = field(default_factory=list)
    layer_url: str = ""
    metadata_url: str = ""
    object_id_field: str | None = None
    max_record_count: int | None = None
    supports_pagination: bool | None = None
    pagination_strategy: str = "single_page"
    pages_requested: int = 0
    features_returned: int = 0
    unique_features: int = 0
    duplicate_features: int = 0
    exceeded_transfer_limit_seen: bool = False
    fallback_used: bool = False
    stop_reason: str = "completed"
    errors: list[str] = field(default_factory=list)
    response_cache_hits: int = 0
    payload: dict[str, Any] = field(default_factory=dict)

    def diagnostic_record(self) -> dict[str, Any]:
        record = asdict(self)
        record.pop("features", None)
        record.pop("payload", None)
        record["endpoint_type"] = "arcgis_layer"
        return record


class ArcGisSyntheticResponse:
    """Small response-compatible wrapper for a combined paginated ArcGIS JSON body."""

    def __init__(self, url: str, data: dict[str, Any], *, status_code: int = 200, content_type: str = "application/json") -> None:
        self.url = url
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self._data = data
        self.text = json.dumps(data, ensure_ascii=False)

    def json(self) -> dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP status {self.status_code} for {self.url}")


def is_arcgis_query_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.path.rstrip("/").casefold().endswith("/query") and any(token in parsed.path.casefold() for token in ("/mapserver/", "/featureserver/"))


def arcgis_layer_url_from_query(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.casefold().endswith("/query"):
        path = path.rsplit("/", 1)[0]
    return parsed._replace(path=path, query="", fragment="").geturl()


def paginate_arcgis_layer(
    layer_url: str,
    *,
    http_client: Any,
    source_policy: Any,
    response_cache: StructuredEndpointResponseCache | None,
    config: ArcGisPaginationConfig,
    diagnostics: list[dict[str, Any]] | None = None,
) -> ArcGisPaginationResult:
    layer_url = arcgis_layer_url_from_query(layer_url)
    result = ArcGisPaginationResult(layer_url=layer_url, metadata_url=_url_with_params(layer_url, {"f": "pjson"}))
    if _is_blocked(source_policy, layer_url):
        result.stop_reason = "source_blocked"
        _append_diag(diagnostics, result)
        return result

    metadata = _fetch_json(result.metadata_url, http_client, response_cache, source_policy, result)
    if isinstance(metadata, dict):
        result.max_record_count = _positive_int(metadata.get("maxRecordCount"))
        result.object_id_field = _object_id_field(metadata)
        raw_adv = metadata.get("advancedQueryCapabilities")
        adv: dict[str, Any] = raw_adv if isinstance(raw_adv, dict) else {}
        result.supports_pagination = bool(adv.get("supportsPagination")) if "supportsPagination" in adv else None
    elif metadata is None:
        result.errors.append("metadata_error")

    strategy = config.strategy
    if strategy == "auto":
        strategy = "offset" if result.supports_pagination is not False else "object_ids"

    if strategy == "single_page":
        _fetch_single_page(layer_url, http_client, response_cache, source_policy, config, result, metadata)
    elif strategy == "object_ids":
        _fetch_by_object_ids(layer_url, http_client, response_cache, source_policy, config, result, metadata, fallback=False)
    else:
        _fetch_by_offset(layer_url, http_client, response_cache, source_policy, config, result, metadata)
        if _should_fallback_after_offset(result, config):
            existing = list(result.features)
            previous_errors = list(result.errors)
            fallback = ArcGisPaginationResult(
                layer_url=result.layer_url,
                metadata_url=result.metadata_url,
                object_id_field=result.object_id_field,
                max_record_count=result.max_record_count,
                supports_pagination=result.supports_pagination,
                fallback_used=True,
                response_cache_hits=result.response_cache_hits,
            )
            _fetch_by_object_ids(layer_url, http_client, response_cache, source_policy, config, fallback, metadata, fallback=True)
            if fallback.features:
                result.features = _dedupe_features(existing + fallback.features, result.object_id_field or fallback.object_id_field or _object_id_field(metadata), result)
                result.pages_requested += fallback.pages_requested
                result.features_returned += fallback.features_returned
                result.unique_features = len(result.features)
                result.fallback_used = True
                result.pagination_strategy = "object_ids" if not existing else "offset_then_object_ids"
                result.stop_reason = fallback.stop_reason
                result.response_cache_hits = fallback.response_cache_hits
            result.errors = previous_errors + fallback.errors

    result.payload = _combined_payload(metadata, result.features)
    result.unique_features = len(result.features)
    _append_diag(diagnostics, result)
    return result


def _fetch_by_offset(layer_url: str, http_client: Any, cache: StructuredEndpointResponseCache | None, source_policy: Any, config: ArcGisPaginationConfig, result: ArcGisPaginationResult, metadata: Any) -> None:
    result.pagination_strategy = "offset"
    page_size = _bounded_size(result.max_record_count, config.page_size, 1000)
    supports_order = bool((metadata or {}).get("advancedQueryCapabilities", {}).get("supportsOrderBy")) if isinstance(metadata, dict) else False
    seen_signatures: set[str] = set()
    offset = 0
    while result.pages_requested < config.max_pages_per_layer:
        if config.max_records_per_layer and len(result.features) >= config.max_records_per_layer:
            result.stop_reason = "record_limit_reached"
            return
        params: dict[str, Any] = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "json", "resultOffset": str(offset), "resultRecordCount": str(page_size)}
        if supports_order and result.object_id_field:
            params["orderByFields"] = result.object_id_field
        url = _url_with_params(f"{layer_url.rstrip('/')}/query", params)
        if _is_blocked(source_policy, url):
            result.stop_reason = "source_blocked"
            return
        page = _fetch_json(url, http_client, cache, source_policy, result)
        result.pages_requested += 1
        if not isinstance(page, dict):
            result.stop_reason = "query_error"
            return
        if _arcgis_error(page):
            result.errors.append(_arcgis_error(page) or "query_error")
            result.stop_reason = "query_error"
            return
        features = _feature_list(page)
        result.features_returned += len(features)
        result.exceeded_transfer_limit_seen = result.exceeded_transfer_limit_seen or bool(page.get("exceededTransferLimit"))
        signature = _page_signature(features, result.object_id_field or _object_id_field(page) or _object_id_field(metadata))
        if signature in seen_signatures:
            result.stop_reason = "repeated_page"
            return
        seen_signatures.add(signature)
        before = len(result.features)
        result.features = _dedupe_features(result.features + features, result.object_id_field or _object_id_field(page) or _object_id_field(metadata), result)
        if not features:
            result.stop_reason = "empty_page"
            return
        if len(result.features) == before:
            result.stop_reason = "all_features_seen"
            return
        if config.max_records_per_layer and len(result.features) >= config.max_records_per_layer:
            result.features = result.features[: config.max_records_per_layer]
            result.stop_reason = "record_limit_reached"
            return
        if page.get("exceededTransferLimit") is False:
            result.stop_reason = "exceeded_transfer_limit_false"
            return
        if len(features) < page_size:
            result.stop_reason = "short_page"
            return
        offset += page_size
    result.stop_reason = "page_limit_reached"


def _fetch_single_page(layer_url: str, http_client: Any, cache: StructuredEndpointResponseCache | None, source_policy: Any, config: ArcGisPaginationConfig, result: ArcGisPaginationResult, metadata: Any) -> None:
    result.pagination_strategy = "single_page"
    params = {"where": "1=1", "outFields": "*", "returnGeometry": "true", "f": "json"}
    page = _fetch_json(_url_with_params(f"{layer_url.rstrip('/')}/query", params), http_client, cache, source_policy, result)
    result.pages_requested += 1
    if not isinstance(page, dict):
        result.stop_reason = "query_error"
        return
    features = _feature_list(page)
    result.features_returned = len(features)
    result.exceeded_transfer_limit_seen = bool(page.get("exceededTransferLimit"))
    result.features = _dedupe_features(features[: config.max_records_per_layer] if config.max_records_per_layer else features, result.object_id_field or _object_id_field(page) or _object_id_field(metadata), result)
    result.stop_reason = "record_limit_reached" if config.max_records_per_layer and len(features) > config.max_records_per_layer else "single_page_strategy"


def _fetch_by_object_ids(layer_url: str, http_client: Any, cache: StructuredEndpointResponseCache | None, source_policy: Any, config: ArcGisPaginationConfig, result: ArcGisPaginationResult, metadata: Any, *, fallback: bool) -> None:
    result.pagination_strategy = "object_ids"
    result.fallback_used = fallback
    ids_url = _url_with_params(f"{layer_url.rstrip('/')}/query", {"where": "1=1", "returnIdsOnly": "true", "f": "json"})
    ids_payload = _fetch_json(ids_url, http_client, cache, source_policy, result)
    result.pages_requested += 1
    if not isinstance(ids_payload, dict) or _arcgis_error(ids_payload):
        if isinstance(ids_payload, dict) and _arcgis_error(ids_payload):
            result.errors.append(_arcgis_error(ids_payload) or "object_id_fallback_error")
        result.stop_reason = "object_id_fallback_error"
        return
    object_ids = [oid for oid in ids_payload.get("objectIds", []) if isinstance(oid, (int, str)) and str(oid).strip()]
    if config.max_records_per_layer:
        object_ids = object_ids[: config.max_records_per_layer]
    if ids_payload.get("objectIdFieldName") and not result.object_id_field:
        result.object_id_field = str(ids_payload.get("objectIdFieldName"))
    batch_size = _bounded_size(result.max_record_count, config.object_id_batch_size, 500)
    max_batches = max(0, config.max_pages_per_layer - result.pages_requested)
    for batch_index, start in enumerate(range(0, len(object_ids), batch_size)):
        if batch_index >= max_batches:
            result.stop_reason = "page_limit_reached"
            return
        if config.max_records_per_layer and len(result.features) >= config.max_records_per_layer:
            result.stop_reason = "record_limit_reached"
            return
        batch = object_ids[start : start + batch_size]
        url = _url_with_params(f"{layer_url.rstrip('/')}/query", {"objectIds": ",".join(str(oid) for oid in batch), "outFields": "*", "returnGeometry": "true", "f": "json"})
        page = _fetch_json(url, http_client, cache, source_policy, result)
        result.pages_requested += 1
        if not isinstance(page, dict) or _arcgis_error(page):
            if isinstance(page, dict) and _arcgis_error(page):
                result.errors.append(_arcgis_error(page) or "object_id_fallback_error")
            result.stop_reason = "object_id_fallback_error"
            return
        features = _feature_list(page)
        result.features_returned += len(features)
        result.exceeded_transfer_limit_seen = result.exceeded_transfer_limit_seen or bool(page.get("exceededTransferLimit"))
        result.features = _dedupe_features(result.features + features, result.object_id_field or _object_id_field(page) or _object_id_field(metadata), result)
    result.stop_reason = "object_id_fallback_completed"


def _fetch_json(url: str, http_client: Any, cache: StructuredEndpointResponseCache | None, source_policy: Any, result: ArcGisPaginationResult) -> Any | None:
    if _is_blocked(source_policy, url):
        result.stop_reason = "source_blocked"
        return None
    try:
        if cache is not None:
            resp, cache_hit = cache.get_or_fetch(url, http_client.get)
            result.response_cache_hits += int(cache_hit)
        else:
            resp = http_client.get(url)
        if getattr(resp, "status_code", 0) >= 400:
            result.errors.append(f"http_status:{getattr(resp, 'status_code', None)}")
            return None
        return json.loads(getattr(resp, "text", ""))
    except Exception as exc:
        result.errors.append(repr(exc))
        return None


def _should_fallback_after_offset(result: ArcGisPaginationResult, config: ArcGisPaginationConfig) -> bool:
    if config.strategy == "offset":
        return False
    return result.stop_reason in {"query_error", "repeated_page", "empty_page", "all_features_seen"} and (result.exceeded_transfer_limit_seen or result.stop_reason == "query_error")


def _combined_payload(metadata: Any, features: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"features": features, "exceededTransferLimit": False}
    if isinstance(metadata, dict):
        for key in ("geometryType", "fields", "spatialReference", "objectIdField", "objectIdFieldName"):
            if key in metadata:
                payload[key] = metadata[key]
    return payload


def _object_id_field(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in ("objectIdField", "objectIdFieldName"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    fields = data.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if isinstance(field, dict) and str(field.get("type") or "").casefold().endswith("oid"):
                name = field.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return None


def _dedupe_features(features: list[Any], object_id_field: str | None, result: ArcGisPaginationResult) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        key = _feature_key(feature, object_id_field)
        if key in seen:
            result.duplicate_features += 1
            continue
        seen.add(key)
        out.append(feature)
    return out


def _feature_key(feature: dict[str, Any], object_id_field: str | None) -> str:
    attrs = feature.get("attributes") if isinstance(feature.get("attributes"), dict) else feature
    for key in [object_id_field, "OBJECTID", "ObjectID", "objectid", "FID"]:
        if key and isinstance(attrs, dict) and key in attrs:
            return f"oid:{attrs[key]}"
    stable = json.dumps(feature, sort_keys=True, separators=(",", ":"), default=str)
    return "hash:" + hashlib.sha256(stable.encode("utf-8")).hexdigest()


def _page_signature(features: list[dict[str, Any]], object_id_field: str | None) -> str:
    keys = [_feature_key(feature, object_id_field) for feature in features if isinstance(feature, dict)]
    return hashlib.sha256("|".join(keys).encode("utf-8")).hexdigest()


def _feature_list(page: Any) -> list[dict[str, Any]]:
    features = page.get("features") if isinstance(page, dict) else None
    return [feature for feature in features if isinstance(feature, dict)] if isinstance(features, list) else []


def _arcgis_error(page: dict[str, Any]) -> str | None:
    error = page.get("error")
    if not isinstance(error, dict):
        return None
    message = error.get("message") or error.get("details") or "arcgis_error"
    return str(message)


def _url_with_params(url: str, params: dict[str, Any]) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in params.items():
        query[str(key)] = [str(value)]
    return parsed._replace(query=urlencode(query, doseq=True), fragment="").geturl()


def _bounded_size(max_record_count: int | None, configured: int, default: int) -> int:
    size = max(1, int(configured or default))
    if max_record_count and max_record_count > 0:
        size = min(size, max_record_count)
    return max(1, size)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _is_blocked(source_policy: Any, url: str) -> bool:
    return bool(source_policy is not None and getattr(source_policy, "is_blocked")(url))


def _append_diag(diagnostics: list[dict[str, Any]] | None, result: ArcGisPaginationResult) -> None:
    if diagnostics is not None:
        diagnostics.append(result.diagnostic_record())
