import json

from camera_discovery.services.harvest_handoff import harvest_records_to_candidates, load_harvest_handoff


def test_harvest_handoff_manifest_loads_inventory_and_converts_candidates(tmp_path):
    inventory = tmp_path / "harvest_camera_inventory.jsonl"
    row = {
        "camera_record_id": "cam:1",
        "camera_id": "cam-1",
        "title": "Main",
        "location_text": "Main Street",
        "lat": 34.0,
        "lon": -118.0,
        "coordinate_source": "geometry:y,x",
        "in_service": True,
        "media_assets": [
            {
                "asset_id": "asset:1",
                "camera_record_id": "cam:1",
                "url": "https://media.example/cam1.m3u8",
                "media_type": "hls",
                "asset_role": "streaming_video",
                "source_endpoint_url": "https://source.example/api",
            }
        ],
        "source_endpoint_url": "https://source.example/api",
        "source_provider": "direct",
        "source_provided_only": True,
        "validated": False,
        "trusted": False,
    }
    inventory.write_text(json.dumps(row) + "\n", encoding="utf-8")
    manifest = tmp_path / "harvest_handoff.json"
    manifest.write_text(
        json.dumps({"schema_version": "harvest-handoff/v1", "files": {"harvest_camera_inventory": "harvest_camera_inventory.jsonl"}}),
        encoding="utf-8",
    )

    records = load_harvest_handoff(manifest)
    candidates = harvest_records_to_candidates(records, target_id="target_1", target_index=0, target_label="Target")
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.stream_url == "https://media.example/cam1.m3u8"
    assert candidate.discovery_method == "harvest_handoff"
    assert candidate.lat == 34.0
    assert candidate.lon == -118.0
    assert candidate.coordinate_source == "geometry:y,x"
    assert candidate.source_metadata["source_provided_only"] is True
    assert candidate.source_metadata["validated"] is False
    assert candidate.source_metadata["trusted"] is False
    assert candidate.source_metadata["asset_role"] == "streaming_video"
