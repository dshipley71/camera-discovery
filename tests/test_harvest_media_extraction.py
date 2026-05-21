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
