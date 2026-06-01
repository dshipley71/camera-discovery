import json

import pytest

from camera_discovery.core.models import DiscoveryMode, HarvestConfig, HarvestedUrlRecord
from camera_discovery.services.harvest_engine import (
    CameraUrlHarvestEngine,
    dedupe_records,
    parse_media_filter,
)


def _engine(tmp_path, media=None, block_patterns=None):
    cfg = HarvestConfig(
        query="test cameras",
        output_dir=tmp_path,
        discovery_mode=DiscoveryMode.DIRECT,
        media=media or [],
        block_patterns=block_patterns or [],
        enable_browser_capture=False,
    )
    return CameraUrlHarvestEngine(cfg)


def test_harvest_extracts_supported_media_types_from_text_variants(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/cameras", "source_provider": "direct", "source_name": "Fixture"}
    text = r"""
    https:\/\/media.example\/a\/playlist.m3u8
    https%3A%2F%2Fmedia.example%2Fb%2Fclip.mp4
    'https://media.example/c/cam.mjpeg'
    "https://media.example/d/current.jpg?rand=1"
    https://media.example/live/stream?id=123
    """
    records = engine._extract_from_text_variants("https://source.example/cameras", row, text, method="fixture")
    by_type = {record.media_type for record in records}
    assert {"hls", "video_file", "mjpeg", "image_snapshot", "stream"}.issubset(by_type)
    assert any(record.url == "https://media.example/a/playlist.m3u8" for record in records)
    assert any(record.url == "https://media.example/b/clip.mp4" for record in records)


def test_harvest_extracts_structured_json_metadata(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/api", "source_provider": "directory", "source_name": "Fixture API"}
    data = {
        "features": [
            {
                "attributes": {
                    "id": "cam-1",
                    "name": "Main Street",
                    "location": "Main and 1st",
                    "stream_url": "https://media.example/live/cam1.m3u8",
                    "refresh_interval": 30,
                }
            }
        ]
    }
    records = engine._extract_from_json_data(data, "https://source.example/api", row, method="json_fixture")
    assert len(records) == 1
    record = records[0]
    assert record.media_type == "hls"
    assert record.camera_id == "cam-1"
    assert record.title == "Main Street"
    assert record.location_text == "Main and 1st"
    assert record.metadata["json_record_path"] == "$.features[0].attributes"
    assert record.metadata["refresh_interval"] == 30


def test_media_filters_match_extensions_and_categories():
    hls = HarvestedUrlRecord(url="https://media.example/a.m3u8", media_type="hls")
    mp4 = HarvestedUrlRecord(url="https://media.example/a.mp4", media_type="video_file")
    image = HarvestedUrlRecord(url="https://media.example/a.jpg", media_type="image_snapshot")
    stream = HarvestedUrlRecord(url="https://media.example/live/stream?id=1", media_type="stream")

    extension_filter = parse_media_filter([".m3u8,mp4"])
    assert extension_filter.matches(hls)
    assert extension_filter.matches(mp4)
    assert not extension_filter.matches(image)

    category_filter = parse_media_filter(["image,stream"])
    assert category_filter.matches(image)
    assert category_filter.matches(stream)
    assert not category_filter.matches(hls)


def test_invalid_media_filter_fails_fast():
    with pytest.raises(ValueError) as exc:
        parse_media_filter(["laserdisc"])
    assert "Unsupported --media" in str(exc.value)
    assert "hls" in str(exc.value)


def test_dedupe_merges_duplicate_metadata():
    records = dedupe_records(
        [
            HarvestedUrlRecord(url="HTTPS://MEDIA.EXAMPLE/cam.m3u8#frag", media_type="hls", source_url="https://source-a.example", metadata={"a": 1}),
            HarvestedUrlRecord(url="https://media.example/cam.m3u8", media_type="hls", source_url="https://source-b.example", title="Camera", metadata={"b": 2}),
        ]
    )
    assert len(records) == 1
    assert records[0].url == "https://media.example/cam.m3u8"
    assert records[0].title == "Camera"
    assert records[0].metadata["a"] == 1
    assert records[0].metadata["b"] == 2
    assert "https://source-b.example" in records[0].metadata["duplicate_sources"]


def test_harvest_promotes_geospatial_orientation_and_datetime_metadata(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/api", "source_provider": "directory", "source_name": "Fixture API"}
    data = {
        "features": [
            {
                "geometry": {"x": -118.2437, "y": 34.0522},
                "attributes": {
                    "id": "cam-geo-1",
                    "name": "Downtown Camera",
                    "stream_url": "https://media.example/live/geo1.m3u8",
                    "direction": "NB",
                    "bearing": 12.5,
                    "last_updated": "2026-05-21T10:15:30Z",
                },
            }
        ]
    }
    records = engine._extract_from_json_data(data, "https://source.example/api", row, method="json_fixture")
    assert len(records) == 1
    record = records[0]
    assert record.lat == 34.0522
    assert record.lon == -118.2437
    assert record.coordinate_source
    assert record.direction == "NB"
    assert record.bearing == 12.5
    assert record.timestamp == "2026-05-21T10:15:30Z"
    assert record.metadata["lat"] == 34.0522
    assert record.metadata["lon"] == -118.2437
    assert record.metadata["direction"] == "NB"
    assert record.metadata["last_updated"] == "2026-05-21T10:15:30Z"


def test_harvest_promotes_lat_lon_from_same_json_record(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/api", "source_provider": "direct", "source_name": "Fixture"}
    data = {
        "cameras": [
            {
                "camera_id": "cam-2",
                "image_url": "https://media.example/cam2.jpg",
                "latitude": "38.8977",
                "longitude": "-77.0365",
                "heading": "270",
                "date": "2026-05-21",
                "time": "13:45:00",
            }
        ]
    }
    records = engine._extract_from_json_data(data, "https://source.example/api", row, method="json_fixture")
    assert len(records) == 1
    record = records[0]
    assert record.lat == 38.8977
    assert record.lon == -77.0365
    assert record.heading == 270
    assert record.date == "2026-05-21"
    assert record.time == "13:45:00"


def test_image_asset_filter_modes():
    from camera_discovery.services.harvest_engine import apply_image_asset_filter

    logo = HarvestedUrlRecord(url="https://static.example/assets/site-logo.png", media_type="image_snapshot")
    camera = HarvestedUrlRecord(
        url="https://media.example/cameras/cam1/current.jpg",
        media_type="image_snapshot",
        camera_record_id="cam:1",
        asset_role="current_image_snapshot",
        asset_field="currentImageURL",
        current_image_update_frequency=30,
    )
    hls = HarvestedUrlRecord(url="https://media.example/cam1/playlist.m3u8", media_type="hls")

    raw_kept, raw_summary = apply_image_asset_filter([logo, camera, hls], "raw")
    assert raw_kept == [logo, camera, hls]
    assert raw_summary["removed"] == 0

    page_filtered, page_summary = apply_image_asset_filter([logo, camera, hls], "exclude-page-assets")
    assert logo not in page_filtered
    assert camera in page_filtered
    assert hls in page_filtered
    assert page_summary["removed_by_reason"] == {"page_asset_evidence": 1}

    evidence_filtered, evidence_summary = apply_image_asset_filter([logo, camera, hls], "camera-evidence")
    assert logo not in evidence_filtered
    assert camera in evidence_filtered
    assert hls in evidence_filtered
    assert evidence_summary["removed_by_reason"] == {"missing_camera_image_evidence": 1}


def test_canonical_media_url_strips_extraction_trailers_and_default_ports():
    from camera_discovery.harvest.media_filter import canonical_media_url

    assert canonical_media_url('https://host.example/live.m3u8\\\\') == 'https://host.example/live.m3u8'
    assert canonical_media_url('https://host.example/live.m3u8\\"') == 'https://host.example/live.m3u8'
    assert canonical_media_url('https://host.example:443/live.m3u8?a=token') == 'https://host.example/live.m3u8?a=token'
    assert canonical_media_url('http://host.example:80/snapshot.jpg') == 'http://host.example/snapshot.jpg'
    assert canonical_media_url('https://host.example:8443/live.m3u8') == 'https://host.example:8443/live.m3u8'


def test_canonical_media_url_prefers_embedded_escaped_scheme_relative_hls():
    from camera_discovery.harvest.media_filter import canonical_media_url
    from camera_discovery.harvest.records import clean_extracted_url

    bad = r"https://source.example/data/cctv/\/\/media.example\/D3\/99_East_Ave.stream\/playlist.m3u8"
    expected = "https://media.example/D3/99_East_Ave.stream/playlist.m3u8"

    assert canonical_media_url(bad) == expected
    assert clean_extracted_url(r"\/\/media.example\/D3\/99_East_Ave.stream\/playlist.m3u8") == expected


def test_harvest_json_extraction_cleans_joined_escaped_hls_url(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/data/cctv/", "source_provider": "directory", "source_name": "Fixture"}
    data = {
        "features": [
            {
                "attributes": {
                    "id": "cam-escaped",
                    "name": "Escaped HLS",
                    "stream_url": r"\/\/media.example\/D3\/99_East_Ave.stream\/playlist.m3u8",
                }
            }
        ]
    }

    records = engine._extract_from_json_data(data, "https://source.example/data/cctv/", row, method="json_fixture")

    assert [record.url for record in records] == ["https://media.example/D3/99_East_Ave.stream/playlist.m3u8"]
