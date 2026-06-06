from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from camera_discovery.extraction.arcgis_pagination import ArcGisPaginationConfig, paginate_arcgis_layer
from camera_discovery.extraction.endpoints import StructuredEndpointResponseCache
from camera_discovery.sources.models import BlockedSource, SourcePolicy

LAYER_URL = "https://example.test/arcgis/rest/services/Traffic/FeatureServer/2"


class FakeResponse:
    def __init__(self, data: dict, status_code: int = 200):
        self.status_code = status_code
        self.text = json.dumps(data)
        self.headers = {"content-type": "application/json"}


class FakeArcGisClient:
    def __init__(self, *, total: int = 0, max_record_count: int = 1000, supports_pagination: bool = True, error_on_offset: bool = False, repeat_offset: bool = False, empty_second_page: bool = False, short_first_page: bool = False, fail_offset: int | None = None):
        self.total = total
        self.max_record_count = max_record_count
        self.supports_pagination = supports_pagination
        self.error_on_offset = error_on_offset
        self.repeat_offset = repeat_offset
        self.empty_second_page = empty_second_page
        self.short_first_page = short_first_page
        self.fail_offset = fail_offset
        self.calls: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.calls.append(url)
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        if parsed.path.rstrip("/") == urlparse(LAYER_URL).path and qs.get("f") == ["pjson"]:
            return FakeResponse(
                {
                    "maxRecordCount": self.max_record_count,
                    "objectIdField": "OBJECTID",
                    "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                    "advancedQueryCapabilities": {"supportsPagination": self.supports_pagination, "supportsOrderBy": True},
                    "geometryType": "esriGeometryPoint",
                }
            )
        if qs.get("returnIdsOnly") == ["true"]:
            return FakeResponse({"objectIdFieldName": "OBJECTID", "objectIds": list(range(1, self.total + 1))})
        if "objectIds" in qs:
            ids = [int(v) for v in qs["objectIds"][0].split(",") if v]
            return FakeResponse({"features": [_feature(i) for i in ids], "exceededTransferLimit": False})
        if self.error_on_offset and "resultOffset" in qs:
            return FakeResponse({"error": {"message": "Pagination is not supported"}})
        offset = int(qs.get("resultOffset", [0])[0])
        count = int(qs.get("resultRecordCount", [self.max_record_count])[0])
        if self.fail_offset is not None and offset >= self.fail_offset:
            return FakeResponse({"error": {"message": "temporary query error"}})
        actual_offset = 0 if self.repeat_offset and offset else offset
        if self.empty_second_page and offset:
            features = []
        else:
            end = min(self.total, actual_offset + count)
            if self.short_first_page and offset == 0:
                end = min(end, max(0, count - 1))
            features = [_feature(i) for i in range(actual_offset + 1, end + 1)]
        return FakeResponse({"features": features, "exceededTransferLimit": offset + count < self.total})


def _feature(object_id: int) -> dict:
    return {"attributes": {"OBJECTID": object_id, "name": f"Camera {object_id}"}, "geometry": {"x": object_id, "y": object_id}}


def _config(**kwargs) -> ArcGisPaginationConfig:
    return ArcGisPaginationConfig(**{"page_size": 1000, "object_id_batch_size": 500, "max_pages_per_layer": 100, "max_records_per_layer": 0, **kwargs})


def test_offset_pagination_retrieves_more_than_1300_records() -> None:
    result = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=1347), source_policy=SourcePolicy(), response_cache=StructuredEndpointResponseCache(), config=_config())

    assert result.unique_features == 1347
    assert result.pages_requested == 2
    assert result.pagination_strategy == "offset"
    assert result.stop_reason == "exceeded_transfer_limit_false"
    assert result.payload["features"] == result.features


def test_offset_stops_on_empty_page_and_short_page() -> None:
    empty = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=2000, empty_second_page=True), source_policy=SourcePolicy(), response_cache=None, config=_config(strategy="offset"))
    short = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=2000, short_first_page=True), source_policy=SourcePolicy(), response_cache=None, config=_config(strategy="offset"))

    assert empty.stop_reason == "empty_page"
    assert short.stop_reason == "short_page"


def test_repeated_pages_do_not_loop_forever() -> None:
    result = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=2500, repeat_offset=True), source_policy=SourcePolicy(), response_cache=None, config=_config(strategy="offset"))

    assert result.stop_reason == "repeated_page"
    assert result.pages_requested == 2


def test_object_id_fallback_when_pagination_unsupported_and_when_offset_errors() -> None:
    unsupported = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=1201, supports_pagination=False), source_policy=SourcePolicy(), response_cache=None, config=_config())
    offset_error = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=20, error_on_offset=True), source_policy=SourcePolicy(), response_cache=None, config=_config())

    assert unsupported.pagination_strategy == "object_ids"
    assert unsupported.unique_features == 1201
    assert unsupported.stop_reason == "object_id_fallback_completed"
    assert offset_error.fallback_used is True
    assert offset_error.unique_features == 20


def test_duplicate_features_are_removed_by_object_id() -> None:
    class DuplicateClient(FakeArcGisClient):
        def get(self, url: str) -> FakeResponse:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "resultOffset" in qs:
                return FakeResponse({"features": [_feature(1), _feature(1)], "exceededTransferLimit": False})
            return super().get(url)

    result = paginate_arcgis_layer(LAYER_URL, http_client=DuplicateClient(total=2), source_policy=SourcePolicy(), response_cache=None, config=_config())

    assert result.unique_features == 1
    assert result.duplicate_features == 1


def test_metadata_max_record_count_controls_page_size() -> None:
    client = FakeArcGisClient(total=1200, max_record_count=250)
    result = paginate_arcgis_layer(LAYER_URL, http_client=client, source_policy=SourcePolicy(), response_cache=None, config=_config(page_size=1000))

    assert result.unique_features == 1200
    assert any("resultRecordCount=250" in url for url in client.calls)


def test_page_and_record_limits_are_enforced() -> None:
    page_limited = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=5000), source_policy=SourcePolicy(), response_cache=None, config=_config(max_pages_per_layer=2))
    record_limited = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=5000), source_policy=SourcePolicy(), response_cache=None, config=_config(max_records_per_layer=1300))

    assert page_limited.stop_reason == "page_limit_reached"
    assert page_limited.unique_features == 2000
    assert record_limited.stop_reason == "record_limit_reached"
    assert record_limited.unique_features == 1300


def test_http_errors_do_not_erase_records_already_collected() -> None:
    result = paginate_arcgis_layer(LAYER_URL, http_client=FakeArcGisClient(total=5000, fail_offset=1000), source_policy=SourcePolicy(), response_cache=None, config=_config(strategy="offset"))

    assert result.stop_reason == "query_error"
    assert result.unique_features == 1000


def test_blocked_source_policy_prevents_pagination_requests() -> None:
    client = FakeArcGisClient(total=10)
    result = paginate_arcgis_layer(LAYER_URL, http_client=client, source_policy=SourcePolicy(blocked_sources=[BlockedSource("example.test", "blocked")]), response_cache=None, config=_config())

    assert result.stop_reason == "source_blocked"
    assert client.calls == []


def test_response_cache_reuses_metadata_and_page_fetches() -> None:
    client = FakeArcGisClient(total=10)
    cache = StructuredEndpointResponseCache()
    first = paginate_arcgis_layer(LAYER_URL, http_client=client, source_policy=SourcePolicy(), response_cache=cache, config=_config())
    second = paginate_arcgis_layer(LAYER_URL, http_client=client, source_policy=SourcePolicy(), response_cache=cache, config=_config())

    assert first.response_cache_hits == 0
    assert second.response_cache_hits >= 2
    assert len(client.calls) == 2
