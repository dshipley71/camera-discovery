import json

from camera_discovery.core.models import DiscoveryMode, HarvestConfig
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.structured_camera_records import extract_structured_camera_records


def _engine(tmp_path):
    return CameraUrlHarvestEngine(
        HarvestConfig(
            query="fixture cameras",
            output_dir=tmp_path,
            discovery_mode=DiscoveryMode.DIRECT,
            enable_browser_capture=False,
        )
    )


def test_structured_arcgis_camera_record_groups_assets_and_metadata(tmp_path):
    engine = _engine(tmp_path)
    row = {"url": "https://source.example/page", "source_provider": "directory", "source_name": "Fixture API"}
    payload = {
        "features": [
            {
                "geometry": {"x": -118.2437, "y": 34.0522},
                "attributes": {
                    "id": "cam-1",
                    "name": "Main Street",
                    "location": "Main and 1st",
                    "inService": True,
                    "imageDescription": "Northbound view",
                    "streamingVideoURL": "https://media.example/cam-1/playlist.m3u8",
                    "currentImageURL": "https://media.example/cam-1/current.jpg",
                    "currentImageUpdateFrequency": 30,
                    "referenceImageUpdateFrequency": 3600,
                    "lastUpdated": "2026-05-21T10:15:30Z",
                    "direction": "NB",
                },
            }
        ]
    }
    records = engine._extract_from_payload("https://source.example/api/cameras", row, json.dumps(payload), "application/json", method="fixture")
    assert len(records) == 2
    camera_ids = {record.camera_record_id for record in records}
    assert len(camera_ids) == 1
    assert {record.asset_role for record in records} == {"streaming_video", "current_image_snapshot"}
    for record in records:
        assert record.camera_id == "cam-1"
        assert record.lat == 34.0522
        assert record.lon == -118.2437
        assert record.in_service is True
        assert record.image_description == "Northbound view"
        assert record.current_image_update_frequency == 30
        assert record.reference_image_update_frequency == 3600
        assert record.timestamp == "2026-05-21T10:15:30Z"
        assert record.direction == "NB"
    assert len(engine._camera_records) == 1
    camera = next(iter(engine._camera_records.values()))
    assert camera.raw_record["attributes"]["streamingVideoURL"] == "https://media.example/cam-1/playlist.m3u8"
    assert camera.field_map["inservice"].endswith("inService")
    assert len(engine._media_assets) == 2
    endpoint = next(iter(engine._discovered_endpoints.values()))
    assert endpoint.camera_record_count == 1
    assert endpoint.media_asset_count == 2
    assert endpoint.has_coordinates is True
    assert endpoint.has_service_status is True
    assert endpoint.has_refresh_metadata is True


def test_geojson_structured_camera_record_preserves_geometry(tmp_path):
    data = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [-77.0365, 38.8977]},
                "properties": {
                    "cameraId": "geo-1",
                    "title": "Geo Camera",
                    "currentImageURL": "https://media.example/geo-1.jpg",
                    "status": "online",
                    "snapshotTimestamp": "2026-05-21T12:00:00Z",
                },
            }
        ],
    }
    records = extract_structured_camera_records(
        data,
        endpoint_url="https://source.example/cameras.geojson",
        source_page_url=None,
        source_provider="direct",
        source_name="Fixture GeoJSON",
    )
    assert len(records) == 1
    record = records[0]
    assert record.camera_id == "geo-1"
    assert record.lat == 38.8977
    assert record.lon == -77.0365
    assert record.status == "online"
    assert record.timestamp == "2026-05-21T12:00:00Z"
    assert len(record.media_assets) == 1
    assert record.media_assets[0].asset_role == "current_image_snapshot"


def test_structured_camera_record_ids_are_deterministic():
    data = {"cameras": [{"cameraId": "stable", "name": "Stable", "currentImageURL": "https://media.example/stable.jpg", "lat": 1, "lon": 2}]}
    first = extract_structured_camera_records(data, endpoint_url="https://source.example/api", source_page_url=None, source_provider="direct", source_name="Fixture")
    second = extract_structured_camera_records(data, endpoint_url="https://source.example/api", source_page_url=None, source_provider="direct", source_name="Fixture")
    assert first[0].camera_record_id == second[0].camera_record_id
    assert first[0].media_assets[0].asset_id == second[0].media_assets[0].asset_id


def test_structured_camera_record_promotes_nested_record_timestamp():
    data = {
        "features": [
            {
                "geometry": {"x": -121.5, "y": 38.5},
                "attributes": {
                    "cameraId": "cam-time-1",
                    "locationName": "Timed Camera",
                    "currentImageURL": "https://media.example/cam-time-1/current.jpg",
                    "recordTimestamp": {
                        "recordDate": "2026-05-21",
                        "recordTime": "14:03:00",
                        "recordEpoch": 1779372180000,
                    },
                },
            }
        ]
    }
    records = extract_structured_camera_records(
        data,
        endpoint_url="https://source.example/api",
        source_page_url=None,
        source_provider="direct",
        source_name="Fixture",
    )
    assert len(records) == 1
    record = records[0]
    assert record.date == "2026-05-21"
    assert record.time == "14:03:00"
    assert record.timestamp == "2026-05-21T14:03:00Z"
    assert record.field_map["recorddate"].endswith("recordTimestamp.recordDate")
    assert record.field_map["recordtime"].endswith("recordTimestamp.recordTime")
    assert record.field_map["recordepoch"].endswith("recordTimestamp.recordEpoch")
    assert record.media_assets[0].date == "2026-05-21"
    assert record.media_assets[0].time == "14:03:00"
    assert record.media_assets[0].timestamp == "2026-05-21T14:03:00Z"
