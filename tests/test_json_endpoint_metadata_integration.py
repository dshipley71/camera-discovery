from __future__ import annotations

import csv

from camera_discovery.core.models import CameraCandidate, CandidateSet, RunConfig, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.services.discovery_engine import CandidateDiscoveryEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.utils.geojson_viewer import write_embedded_camera_map


def _cfg(tmp_path):
    return RunConfig(query="Get public cameras from Example", output_dir=tmp_path)


def test_json_endpoint_streaming_video_url_uses_metadata_and_not_playlist_id(tmp_path):
    engine = CandidateDiscoveryEngine(_cfg(tmp_path))
    data = {
        "cameras": [
            {
                "cameraID": "CAM-123",
                "cameraType": "Weather camera",
                "locationDescription": "Example Ridge",
                "streamingVideoURL": "https://media.example/d1/example_ridge.stream/playlist.m3u8",
                "currentImageUpdateFrequency": 15,
                "lat": 38.1,
                "lon": -121.2,
            }
        ]
    }

    rows = engine._extract_from_json_data(data, "https://public.example/cameras.json", {"url": "https://public.example/cameras.json"}, "json_endpoint")

    assert len(rows) == 1
    row = rows[0]
    assert row.stream_url.endswith("playlist.m3u8")
    assert row.source_metadata["json_metadata_extracted"] is True
    assert row.source_metadata["json_endpoint_url"] == "https://public.example/cameras.json"
    assert row.source_metadata["camera_id"] == "CAM-123"
    assert row.source_metadata["camera_id"] != "playlist"
    assert row.source_metadata["camera_type"] == "weather"
    assert row.source_metadata["raw_camera_type"] == "Weather camera"
    assert row.source_metadata["camera_refresh_rate"] == 15
    assert row.lat == 38.1
    assert row.lon == -121.2
    assert row.coordinate_source == "source_record"


def test_json_snapshot_refresh_metadata_flows_to_table_and_geojson(tmp_path):
    cfg = _cfg(tmp_path)
    engine = CandidateDiscoveryEngine(cfg)
    data = {
        "cameras": [
            {
                "id": "snap-1",
                "name": "Example Snapshot",
                "cameraType": "traffic",
                "currentImageURL": "https://images.example/snap-1.jpg",
                "currentImageUpdateFrequency": 15,
                "latitude": 37.5,
                "longitude": -122.1,
                "route": "I-5",
                "direction": "NB",
            }
        ]
    }
    rows = engine._extract_from_json_data(data, "https://public.example/snapshots.json", {"url": "https://public.example/snapshots.json"}, "json_endpoint")
    target = TargetContext(
        user_query=cfg.query,
        intent=TargetIntent(raw_query=cfg.query, canonical_target="Example"),
        target_id="example",
        target_label="Example",
        bbox_verified=True,
        trust_policy=TrustPolicy.TRUSTED_ALLOWED,
    )
    candidate = rows[0]
    candidate.target_id = target.target_id
    candidate.target_label = target.target_label
    candidate.scope_status = "in_scope"
    candidate.trust_level = "trusted"
    candidate.validation_status = "active_image_snapshot_refreshing"

    pipeline = ReviewAndValidationPipeline(cfg)
    pipeline._write_candidate_table([candidate])
    pipeline._write_geojson(tmp_path / "camera.geojson", [candidate], trusted=True, target_map={target.target_id: target})

    table_rows = list(csv.DictReader((tmp_path / "camera_candidates_table.csv").open(encoding="utf-8", newline="")))
    assert table_rows[0]["json_endpoint_url"] == "https://public.example/snapshots.json"
    assert table_rows[0]["route"] == "I-5"
    assert table_rows[0]["direction"] == "NB"
    assert table_rows[0]["camera_refresh_rate"] == "15"
    assert table_rows[0]["map_refresh_rate_seconds"] == "15"
    geojson = (tmp_path / "camera.geojson").read_text(encoding="utf-8")
    assert '"map_refresh_rate_seconds": 15' in geojson
    assert '"json_endpoint_url": "https://public.example/snapshots.json"' in geojson


def test_map_renders_trusted_star_and_untrusted_circle_with_json_metadata(tmp_path):
    (tmp_path / "camera.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-100,40]},"properties":{"stream_url":"https://public.example/live.m3u8","media_type":"hls","camera_type":"traffic","trust_level":"trusted","trusted_geojson_candidate":true,"json_endpoint_url":"https://public.example/feed.json","route":"I-5"}}]}',
        encoding="utf-8",
    )
    (tmp_path / "untrusted_camera_candidates.geojson").write_text(
        '{"type":"FeatureCollection","features":[{"type":"Feature","geometry":{"type":"Point","coordinates":[-101,41]},"properties":{"stream_url":"https://public.example/cam.jpg","media_type":"image_snapshot","camera_type":"traffic","trust_level":"untrusted","json_endpoint_url":"https://public.example/feed.json"}}]}',
        encoding="utf-8",
    )

    html = write_embedded_camera_map(tmp_path).read_text(encoding="utf-8")

    assert "trustedStarIcon" in html
    assert "markerForFeature" in html
    assert "source JSON" in html
    assert "Source metadata" in html
    assert "Camera color legend" in html
    assert "Traffic / HLS video fallback" in html
