from __future__ import annotations

from pathlib import Path

from camera_discovery.core.models import CameraCandidate
from camera_discovery.passive_intelligence import (
    candidate_evidence_record,
    classify_protocol,
    enrich_candidate_with_passive_intelligence,
    enrich_source_row_with_passive_intelligence,
    http_metadata_from_response,
    match_signatures,
    passive_intelligence_summary,
    redact_sensitive_url,
)


class _Response:
    status_code = 200
    url = "https://public.example/cameras?token=secret&ok=1"
    history = [object()]
    headers = {
        "content-type": "text/html",
        "server": "nginx",
        "set-cookie": "do-not-store",
        "authorization": "do-not-store",
        "www-authenticate": 'Basic realm="Camera"',
    }


def test_safe_signatures_match_existing_evidence_without_generating_urls() -> None:
    matches = match_signatures("https://public.example/axis-cgi/mjpg/video.cgi?token=secret", "Traffic cameras")

    families = {match["signature_family"] for match in matches}
    assert "camera_path_fragment" in families
    assert "mjpeg_path_fragment" in families
    assert all("credential" not in match["matched_value"].casefold() for match in matches)
    assert all("cve" not in match["matched_value"].casefold() for match in matches)
    assert all("probe" not in match["reason"].casefold() for match in matches)


def test_protocol_labeling_is_passive_and_deterministic() -> None:
    assert classify_protocol("https://media.example/live/master.m3u8")["protocol_label"] == "hls"
    assert classify_protocol("rtsp://public.example/live/stream")["protocol_label"] == "rtsp"
    assert classify_protocol("https://media.example/cam.jpg", metadata={"camera_type": "weather"})["protocol_label"] == "image_snapshot"
    assert classify_protocol("https://media.example/mjpg/video", content_type="multipart/x-mixed-replace; boundary=frame")["protocol_label"] == "mjpeg"
    assert classify_protocol("https://media.example/live/stream")["protocol_label"] == "unknown_stream"


def test_http_metadata_allowlist_and_redaction() -> None:
    metadata = http_metadata_from_response(_Response(), text="<html><title>Traffic Cameras</title></html>")

    assert metadata["http_status"] == 200
    assert metadata["final_url"] == "https://public.example/cameras?token=%2A%2A%2A&ok=1"
    assert metadata["title"] == "Traffic Cameras"
    assert metadata["www_authenticate_present"] is True
    assert metadata["auth_realm"] == "Camera"
    assert "set-cookie" not in metadata["headers"]
    assert "authorization" not in metadata["headers"]
    assert redact_sensitive_url("rtsp://user:pass@public.example/live?api_key=secret") == "rtsp://***:***@public.example/live?api_key=%2A%2A%2A"


def test_evidence_scoring_is_explainable_and_does_not_create_trust() -> None:
    candidate = CameraCandidate(
        stream_url="https://media.example/cameras/master.m3u8",
        source_url="https://public.example/cameras.json",
        title="Main Street traffic camera",
        lat=38.0,
        lon=-77.0,
        source_metadata={
            "media_type": "hls",
            "json_endpoint_url": "https://public.example/cameras.json",
            "camera_id": "cam-1",
            "direction": "north",
        },
    )

    enrich_candidate_with_passive_intelligence(candidate)

    metadata = candidate.source_metadata
    assert metadata["camera_evidence_score"] >= 75
    assert metadata["camera_evidence_band"] == "very_strong"
    assert metadata["protocol_label"] == "hls"
    assert candidate.trust_level == "untrusted"
    assert candidate.validation_status is None
    assert candidate_evidence_record(candidate)["why_it_mattered"]


def test_source_row_scoring_and_summary() -> None:
    row = enrich_source_row_with_passive_intelligence(
        {"url": "https://public.example/MapServer/cameras?f=json", "title": "Public traffic camera API json", "source_provider": "directory"}
    )

    assert row["source_camera_evidence_score"] >= 40
    assert row["source_camera_evidence_reasons"]
    assert row["source_signature_matches"]


def test_passive_summary_counts_bands_protocols_and_reasons() -> None:
    hls = CameraCandidate(stream_url="https://media.example/live.m3u8", source_metadata={"media_type": "hls"})
    image = CameraCandidate(stream_url="https://media.example/snapshot.jpg", source_metadata={"media_type": "image_snapshot"})
    enrich_candidate_with_passive_intelligence(hls)
    enrich_candidate_with_passive_intelligence(image)

    summary = passive_intelligence_summary([hls, image])

    assert summary["candidates_scored"] == 2
    assert summary["protocol_label_counts"]["hls"] == 1
    assert summary["protocol_label_counts"]["image_snapshot"] == 1
    assert summary["top_camera_evidence_reasons"]


def test_no_active_scanning_or_bruteforce_modules_added() -> None:
    passive_dir = Path("src/camera_discovery/passive_intelligence")
    text = "\n".join(path.read_text(encoding="utf-8").casefold() for path in passive_dir.glob("*.py"))
    forbidden_runtime_tokens = ["import socket", "import subprocess", "masscan", "nmap", "tcpdump", "tshark"]
    assert not any(token in text for token in forbidden_runtime_tokens)
    assert "default password" not in text
