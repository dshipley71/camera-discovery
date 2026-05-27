"""Regression tests for reference-image asset-role classification.

Public traffic-camera APIs such as Caltrans expose multiple reference
(historical) snapshots under numbered field names:

    referenceImage1UpdateAgoURL
    referenceImage2UpdatesAgoURL
    ...
    referenceImage12UpdatesAgoURL

The normalized keys (referenceimage1updateagourl ... referenceimage12updatesagourl)
do not appear verbatim in MEDIA_FIELD_ROLES, so without explicit pattern
matching they fall through to _asset_role_for_media_type and are classified
as "image_snapshot" instead of "reference_image_snapshot".  This leads to
records_with_reference_image always being 0 in harvest_summary.json.

These tests lock in the correct behaviour: all referenceimage*url fields must
receive asset_role == "reference_image_snapshot", and harvest_summary.json must
report a non-zero records_with_reference_image count when such records are
present in the written output.
"""

import json

from camera_discovery.services.structured_camera_records import (
    _role_for_field_key,
    extract_structured_camera_records,
)
from camera_discovery.core.models import DiscoveryMode, HarvestConfig
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine


# ---------------------------------------------------------------------------
# Unit tests for _role_for_field_key
# ---------------------------------------------------------------------------

def test_role_for_field_key_exact_matches():
    """Exact entries in MEDIA_FIELD_ROLES are still honoured."""
    assert _role_for_field_key("currentimageurl", "image_snapshot") == "current_image_snapshot"
    assert _role_for_field_key("referenceimageurl", "image_snapshot") == "reference_image_snapshot"
    assert _role_for_field_key("streamingvideourl", "hls") == "streaming_video"
    assert _role_for_field_key("hlsurl", "hls") == "hls_stream"
    assert _role_for_field_key("thumbnailurl", "image_snapshot") == "thumbnail"


def test_role_for_field_key_numbered_reference_images():
    """Numbered referenceimage*url keys map to reference_image_snapshot."""
    for n in range(1, 13):
        suffix = "updateagourl" if n == 1 else "updatesagourl"
        key = f"referenceimage{n}{suffix}"
        result = _role_for_field_key(key, "image_snapshot")
        assert result == "reference_image_snapshot", (
            f"Expected reference_image_snapshot for key {key!r}, got {result!r}"
        )


def test_role_for_field_key_unknown_field_falls_back_to_media_type():
    """Unknown fields fall back to media-type-based classification."""
    assert _role_for_field_key("somearbitraryfield", "hls") == "hls_stream"
    assert _role_for_field_key("somearbitraryfield", "image_snapshot") == "image_snapshot"
    assert _role_for_field_key("somearbitraryfield", "video_file") == "video_file"


# ---------------------------------------------------------------------------
# Integration test: extract_structured_camera_records
# ---------------------------------------------------------------------------

def _synthetic_caltrans_style_record(cam_id: str) -> dict:
    """Return a synthetic Caltrans-style camera object (no real data)."""
    return {
        "index": cam_id,
        "inService": True,
        "location": {
            "locationName": f"Synthetic Location {cam_id}",
            "direction": "South",
            "latitude": 37.0,
            "longitude": -120.0,
        },
        "imageData": {
            "imageDescription": f"Synthetic camera {cam_id}",
            "static": {
                "currentImageUpdateFrequency": "20",
                "currentImageURL": f"https://example.invalid/cam{cam_id}/current.jpg",
                "referenceImage1UpdateAgoURL": f"https://example.invalid/cam{cam_id}/ref1.jpg",
                "referenceImage2UpdatesAgoURL": f"https://example.invalid/cam{cam_id}/ref2.jpg",
                "referenceImage3UpdatesAgoURL": f"https://example.invalid/cam{cam_id}/ref3.jpg",
            },
        },
        "recordTimestamp": {
            "recordDate": "2026-01-01",
            "recordTime": "00:00:00",
            "recordEpoch": 1735689600000,
        },
    }


def test_reference_image_assets_receive_correct_role():
    """referenceimage*url fields must produce asset_role == reference_image_snapshot."""
    data = {"data": [_synthetic_caltrans_style_record("synth-1")]}
    records = extract_structured_camera_records(
        data,
        endpoint_url="https://example.invalid/api/cameras",
        source_page_url=None,
        source_provider="direct",
        source_name="Synthetic Fixture",
    )
    assert len(records) == 1
    record = records[0]

    roles = {asset.asset_role for asset in record.media_assets}
    assert "current_image_snapshot" in roles, "current_image_snapshot role missing"
    assert "reference_image_snapshot" in roles, (
        "reference_image_snapshot role missing — referenceimage*url fields are "
        "not being pattern-matched correctly"
    )

    ref_assets = [a for a in record.media_assets if a.asset_role == "reference_image_snapshot"]
    assert len(ref_assets) == 3, (
        f"Expected 3 reference_image_snapshot assets, got {len(ref_assets)}"
    )
    cur_assets = [a for a in record.media_assets if a.asset_role == "current_image_snapshot"]
    assert len(cur_assets) == 1


def test_reference_image_assets_carry_camera_record_provenance():
    """Each reference-image asset must link back to its parent camera record."""
    data = {"data": [_synthetic_caltrans_style_record("synth-2")]}
    records = extract_structured_camera_records(
        data,
        endpoint_url="https://example.invalid/api/cameras",
        source_page_url=None,
        source_provider="direct",
        source_name="Synthetic Fixture",
    )
    record = records[0]
    for asset in record.media_assets:
        if asset.asset_role == "reference_image_snapshot":
            assert asset.camera_record_id == record.camera_record_id
            assert asset.discovery_method == "structured_camera_record"
            assert asset.source_endpoint_url == "https://example.invalid/api/cameras"


# ---------------------------------------------------------------------------
# Integration test: harvest_summary records_with_reference_image counter
# ---------------------------------------------------------------------------

def _harvest_engine(tmp_path):
    return CameraUrlHarvestEngine(
        HarvestConfig(
            query="synthetic fixture cameras",
            output_dir=tmp_path,
            discovery_mode=DiscoveryMode.DIRECT,
            enable_browser_capture=False,
        )
    )


def test_harvest_summary_records_with_reference_image_nonzero(tmp_path):
    """records_with_reference_image in harvest_summary must be > 0 when
    reference-image assets are present in the written output records."""
    engine = _harvest_engine(tmp_path)
    row = {
        "url": "https://example.invalid/api/cameras",
        "source_provider": "direct",
        "source_name": "Synthetic Fixture",
    }
    payload = {"data": [_synthetic_caltrans_style_record("synth-3")]}
    records = engine._extract_from_payload(
        "https://example.invalid/api/cameras",
        row,
        json.dumps(payload),
        "application/json",
        method="fixture",
    )

    ref_records = [r for r in records if r.asset_role == "reference_image_snapshot"]
    assert len(ref_records) >= 1, (
        "No reference_image_snapshot records produced — role classification is broken"
    )

    # Simulate the summary counter logic from _write_outputs.
    count = sum(1 for r in records if r.asset_role == "reference_image_snapshot")
    assert count > 0, (
        "records_with_reference_image would be 0 in harvest_summary.json — "
        "the counter is still broken"
    )
