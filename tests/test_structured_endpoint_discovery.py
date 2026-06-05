from __future__ import annotations

from camera_discovery.extraction.endpoints import (
    StructuredEndpointRef,
    expand_structured_endpoint_refs_from_metadata,
    extract_structured_endpoint_refs_from_text,
    linked_script_urls_from_html,
)
from camera_discovery.extraction.pagination import _expand_structured_endpoint_urls


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
