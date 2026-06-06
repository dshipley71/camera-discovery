from __future__ import annotations

import json

from camera_discovery.core.models import HarvestConfig, RunConfig
from camera_discovery.extraction.endpoints import (
    StructuredEndpointRef,
    expand_structured_endpoint_refs_from_metadata,
    extract_structured_endpoint_refs_from_text,
    linked_script_urls_from_html,
)
from camera_discovery.extraction.pagination import _expand_structured_endpoint_urls
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine


def test_arcgis_service_expands_only_advertised_layers() -> None:
    fetched: list[str] = []

    def fetch_json(url: str):
        fetched.append(url)
        return {
            "layers": [{"id": 2, "name": "Cameras"}, {"id": 9, "name": "Signs"}],
            "tables": [{"id": 12, "name": "Camera metadata"}],
        }

    refs = expand_structured_endpoint_refs_from_metadata(
        [StructuredEndpointRef("https://example.test/arcgis/rest/services/Traffic/MapServer", "arcgis_service", "fixture")],
        fetch_json=fetch_json,
        max_endpoints=10,
    )
    urls = [ref.url for ref in refs]

    assert fetched == ["https://example.test/arcgis/rest/services/Traffic/MapServer?f=pjson"]
    assert "https://example.test/arcgis/rest/services/Traffic/MapServer/2/query?where=1%3D1&outFields=*&returnGeometry=true&f=json" in urls
    assert "https://example.test/arcgis/rest/services/Traffic/MapServer/9/query?where=1%3D1&outFields=*&returnGeometry=true&f=json" in urls
    assert "https://example.test/arcgis/rest/services/Traffic/MapServer/12/query?where=1%3D1&outFields=*&returnGeometry=true&f=json" in urls
    assert not any("/0/query" in url for url in urls)
    assert not any("/1/query" in url for url in urls)


def test_legacy_expander_does_not_guess_arcgis_layer_ids() -> None:
    urls = _expand_structured_endpoint_urls(["https://example.test/arcgis/rest/services/Traffic/FeatureServer"])

    assert urls == ["https://example.test/arcgis/rest/services/Traffic/FeatureServer"]


def test_explicit_script_bundle_endpoint_extraction() -> None:
    html = '<html><script src="/static/app.js"></script><script src="/static/not-css.css"></script></html>'
    scripts = linked_script_urls_from_html(html, "https://example.test/map/")

    assert scripts == ["https://example.test/static/app.js"]

    js = "const cameraFeed = '/api/cameras.geojson'; fetch('/arcgis/rest/services/CCTV/FeatureServer');"
    refs = extract_structured_endpoint_refs_from_text(js, "https://example.test/static/app.js")
    urls = [ref.url for ref in refs]

    assert "https://example.test/api/cameras.geojson" in urls
    assert "https://example.test/arcgis/rest/services/CCTV/FeatureServer" in urls


def test_ogc_collections_expand_to_advertised_items_links() -> None:
    def fetch_json(url: str):
        return {
            "collections": [
                {"id": "cameras", "links": [{"rel": "items", "type": "application/geo+json", "href": "./cameras/items?f=json"}]},
            ]
        }

    refs = expand_structured_endpoint_refs_from_metadata(
        ["https://example.test/ogc/collections"],
        fetch_json=fetch_json,
        max_endpoints=10,
    )
    urls = [ref.url for ref in refs]

    assert "https://example.test/ogc/cameras/items?f=json" in urls
    assert "https://example.test/ogc/collections/cameras/items?f=json" in urls


class _Response:
    def __init__(self, data: dict):
        self.status_code = 200
        self.text = json.dumps(data)
        self.headers = {"content-type": "application/json"}


class _ArcGisWorkflowClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, url: str) -> _Response:
        self.calls.append(url)
        if url.endswith("/FeatureServer?f=pjson"):
            return _Response({"layers": [{"id": 0, "name": "Cameras"}]})
        if url.endswith("/FeatureServer/0?f=pjson"):
            return _Response({"maxRecordCount": 1, "objectIdField": "OBJECTID", "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}], "advancedQueryCapabilities": {"supportsPagination": True, "supportsOrderBy": True}})
        if "resultOffset=0" in url:
            return _Response({"features": [{"attributes": {"OBJECTID": 1, "imageUrl": "https://media.example.test/cam1.jpg", "name": "Camera One"}, "geometry": {"x": -75.0, "y": 40.0}}], "exceededTransferLimit": True})
        if "resultOffset=1" in url:
            return _Response({"features": [{"attributes": {"OBJECTID": 2, "imageUrl": "https://media.example.test/cam2.jpg", "name": "Camera Two"}, "geometry": {"x": -75.1, "y": 40.1}}], "exceededTransferLimit": False})
        raise AssertionError(f"unexpected URL {url}")


def test_normal_discovery_uses_shared_arcgis_paginator(tmp_path) -> None:
    engine = CandidateDiscoveryEngine(RunConfig(query="traffic cameras", output_dir=tmp_path, enable_browser_capture=False, sources_file=None, block_patterns=[]))
    engine.logs_dir.mkdir(parents=True, exist_ok=True)
    client = _ArcGisWorkflowClient()
    html = '<script>fetch("https://example.test/arcgis/rest/services/CCTV/FeatureServer")</script>'

    candidates = engine._extract_from_linked_feeds("https://example.test/map", {"url": "https://example.test/map"}, html, client)  # noqa: SLF001

    assert len(candidates) == 2
    assert any("resultOffset=1" in call for call in client.calls)


def test_harvest_mode_uses_shared_arcgis_paginator(tmp_path) -> None:
    engine = CameraUrlHarvestEngine(HarvestConfig(query="traffic cameras", output_dir=tmp_path, enable_browser_capture=False, sources_file=None, block_patterns=[]))
    engine.output_dir.mkdir(parents=True, exist_ok=True)
    engine.logs_dir.mkdir(parents=True, exist_ok=True)
    client = _ArcGisWorkflowClient()
    html = '<script>fetch("https://example.test/arcgis/rest/services/CCTV/FeatureServer")</script>'

    records = engine._extract_linked_endpoints("https://example.test/map", {"url": "https://example.test/map"}, html, client)  # noqa: SLF001

    assert len(records) == 2
    assert any("resultOffset=1" in call for call in client.calls)
