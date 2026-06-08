from __future__ import annotations

import json
import subprocess
from zipfile import ZipFile

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, HarvestConfig, HarvestedUrlRecord, RunConfig, RuntimeProfile, TargetContext, TargetIntent, TrustPolicy
from camera_discovery.harvest.media_filter import classify_media_url, parse_media_filter
from camera_discovery.services.harvest_engine import CameraUrlHarvestEngine
from camera_discovery.services.review_validation_pipeline import ReviewAndValidationPipeline
from camera_discovery.utils.playlists import build_media_validation_dashboard, export_candidate_playlists
from camera_discovery.utils.url_safety import is_private_or_local_media_url, redact_url_userinfo


def _target(query: str = "Get public cameras from Example City") -> TargetContext:
    return TargetContext(
        user_query=query,
        intent=TargetIntent(raw_query=query, canonical_target="Example City", camera_type_intent="public_live"),
        target_id="example_city",
        target_label="Example City",
        canonical_target="Example City",
        trust_policy=TrustPolicy.TRUSTED_ALLOWED,
        bbox_verified=True,
    )


def _cfg(tmp_path, **overrides) -> RunConfig:
    kwargs = {
        "query": "Get public cameras from Example City",
        "output_dir": tmp_path,
        "profile": RuntimeProfile.BALANCED,
        "llm_provider": "ollama",
        "llm_model": "gemma3:12b-cloud",
        "validation_workers": 1,
        "http_timeout": 1,
    }
    kwargs.update(overrides)
    return RunConfig(**kwargs)


def test_rtsp_classification_filtering_and_extraction(tmp_path):
    assert classify_media_url("rtsp://public.example/live/stream") == "rtsp"
    assert classify_media_url("rtsps://public.example/live/stream") == "rtsp"

    rtsp = CameraCandidate(stream_url="rtsp://public.example/live/stream", source_metadata={"media_type": "rtsp"})
    rtsp_record = HarvestedUrlRecord(url=rtsp.stream_url, media_type="rtsp")
    assert parse_media_filter(["rtsp"]).matches(rtsp_record)
    assert parse_media_filter(["stream"]).matches(rtsp_record)

    engine = CameraUrlHarvestEngine(
        HarvestConfig(
            query="Example City cameras",
            output_dir=tmp_path,
            discovery_mode=DiscoveryMode.DIRECT,
            enable_browser_capture=False,
        )
    )
    row = {"url": "https://source.example/cameras", "source_provider": "direct", "source_name": "Fixture"}
    records = engine._extract_from_text_variants(
        "https://source.example/cameras",
        row,
        '{"stream_url":"rtsp://public.example/live/stream?token=keep"}',
        method="fixture",
    )
    assert any(record.media_type == "rtsp" and record.url == "rtsp://public.example/live/stream?token=keep" for record in records)
    assert is_private_or_local_media_url("rtsp://127.0.0.1/live")
    assert redact_url_userinfo("rtsp://user:secret@public.example/live") == "rtsp://***:***@public.example/live"


def test_playlist_writer_dashboard_and_review_zip(tmp_path, monkeypatch):
    target = _target()
    trusted = CameraCandidate(
        stream_url="https://media.example/trusted.m3u8",
        source_url="https://source.example/cameras",
        title="Trusted Camera",
        lat=38.0,
        lon=-77.0,
        scope_status="in_scope",
        target_id=target.target_id,
        target_label=target.target_label,
        source_metadata={"media_type": "hls"},
    )
    rtsp_review = CameraCandidate(
        stream_url="rtsp://public.example/live/review",
        source_url="https://source.example/cameras",
        title="RTSP Review",
        lat=38.1,
        lon=-77.1,
        scope_status="review",
        target_id=target.target_id,
        target_label=target.target_label,
        source_metadata={"media_type": "rtsp", "asset_role": "rtsp_stream"},
    )
    restricted = CameraCandidate(
        stream_url="https://media.example/restricted.m3u8",
        source_url="https://source.example/cameras",
        title="Restricted Camera",
        lat=38.2,
        lon=-77.2,
        scope_status="review",
        target_id=target.target_id,
        target_label=target.target_label,
        source_metadata={"media_type": "hls"},
    )
    candidates = CandidateSet(unique=[trusted, rtsp_review, restricted], review=[trusted, rtsp_review, restricted])

    def fake_validate(candidate: CameraCandidate) -> str:
        if "trusted" in candidate.stream_url:
            return "active_live_verified"
        if candidate.stream_url.startswith("rtsp://"):
            return "active_rtsp_verified"
        return "restricted_http"

    monkeypatch.setattr(ReviewAndValidationPipeline, "_validate_candidate", lambda self, candidate: fake_validate(candidate))
    _, outputs = ReviewAndValidationPipeline(_cfg(tmp_path)).run([target], candidates)

    assert (tmp_path / "playlists" / "trusted_media.m3u").exists()
    assert "Trusted Camera" in (tmp_path / "playlists" / "trusted_media.m3u").read_text(encoding="utf-8")
    assert (tmp_path / "playlists" / "rtsp_candidates.m3u").read_text(encoding="utf-8").count("rtsp://public.example/live/review") == 1
    assert not (tmp_path / "playlists" / "dead_or_restricted_media.m3u").exists()
    assert "https://media.example/restricted.m3u8" in (tmp_path / "playlists" / "dead_or_restricted_media.txt").read_text(encoding="utf-8")

    summary = json.loads((tmp_path / "logs" / "playlist_export_summary.json").read_text(encoding="utf-8"))
    assert summary["counts"]["trusted_media"] == 1
    assert summary["counts"]["rtsp_candidates"] == 1

    dashboard = json.loads((tmp_path / "media_validation_dashboard.json").read_text(encoding="utf-8"))
    assert {"total_candidates", "validated", "trusted", "untrusted_review", "dead", "restricted", "not_validated"}.issubset(dashboard)
    assert dashboard["total_candidates"] == 3
    assert dashboard["validated"] == 3
    assert dashboard["trusted"] == 1
    assert dashboard["restricted"] == 1
    assert outputs.playlist_export_summary
    assert outputs.media_validation_dashboard

    explanation = json.loads((tmp_path / "logs" / "run_explanation.json").read_text(encoding="utf-8"))
    assert explanation["media_validation_dashboard"]["total_candidates"] == 3
    with ZipFile(tmp_path / "review_artifacts.zip") as zf:
        names = set(zf.namelist())
    assert "media_validation_dashboard.json" in names
    assert "logs/playlist_export_summary.json" in names
    assert "playlists/rtsp_candidates.m3u" in names


def test_run_start_initializes_expected_empty_media_outputs(tmp_path):
    from camera_discovery.runners.discovery_run import _initialize_expected_media_outputs

    cfg = _cfg(tmp_path, enable_google_dorking=True)
    _initialize_expected_media_outputs(cfg)

    assert (tmp_path / "media_validation_dashboard.json").exists()
    assert (tmp_path / "logs" / "media_validation_dashboard.json").exists()
    assert (tmp_path / "logs" / "playlist_export_summary.json").exists()
    assert (tmp_path / "logs" / "google_dorking_summary.json").exists()
    assert (tmp_path / "playlists").is_dir()
    dashboard = json.loads((tmp_path / "media_validation_dashboard.json").read_text(encoding="utf-8"))
    assert dashboard["total_candidates"] == 0
    assert dashboard["validated"] == 0
    assert dashboard["trusted"] == 0
    assert dashboard["untrusted_review"] == 0
    assert dashboard["dead"] == 0
    assert dashboard["restricted"] == 0
    assert dashboard["not_validated"] == 0
    assert dashboard["by_media_type"] == {}
    assert dashboard["by_validation_status"] == {}
    assert dashboard["passive_intelligence"]["candidates_scored"] == 0
    dorking = json.loads((tmp_path / "logs" / "google_dorking_summary.json").read_text(encoding="utf-8"))
    assert dorking["enabled"] is True
    assert dorking["queries_generated"] == 0


def test_rtsp_validation_statuses_are_safe_and_bounded(tmp_path, monkeypatch):
    pipeline = ReviewAndValidationPipeline(_cfg(tmp_path))
    calls = []

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.shutil.which", lambda name: "/usr/bin/ffprobe")

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"streams":[{"codec_type":"video"}]}', stderr="")

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.subprocess.run", fake_run)
    assert pipeline._validate_rtsp("rtsp://public.example/live") == "active_rtsp_verified"
    assert calls

    calls.clear()
    assert pipeline._validate_rtsp("rtsp://127.0.0.1/live") == "restricted_rtsp"
    assert calls == []

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.shutil.which", lambda name: None)
    assert pipeline._validate_rtsp("rtsp://public.example/live") == "rtsp_validation_unavailable"

    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.shutil.which", lambda name: "/usr/bin/ffprobe")
    monkeypatch.setattr("camera_discovery.services.review_validation_pipeline.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)))
    assert pipeline._validate_rtsp("rtsp://public.example/live") == "offline_rtsp"


def test_private_and_blocked_urls_are_excluded_from_playlist_helpers(tmp_path):
    trusted = CameraCandidate(stream_url="https://public.example/live.m3u8", title="Public", source_metadata={"media_type": "hls"}, target_id="t")
    private = CameraCandidate(stream_url="rtsp://192.168.1.10/live", title="Private", source_metadata={"media_type": "rtsp"}, target_id="t")
    summary = export_candidate_playlists(tmp_path, [trusted, private], trusted_candidates=[trusted, private], review_candidates=[])
    assert summary["counts"]["trusted_media"] == 1
    assert "192.168" not in (tmp_path / "playlists" / "trusted_media.txt").read_text(encoding="utf-8")

    dashboard = build_media_validation_dashboard(
        [
            CameraCandidate(stream_url="https://public.example/live.m3u8", validation_status="active_live_verified", trust_level="trusted", source_metadata={"media_type": "hls"}),
            CameraCandidate(stream_url="https://public.example/dead.m3u8", validation_status="dead_link", source_metadata={"media_type": "hls"}),
            CameraCandidate(stream_url="rtsp://public.example/auth", validation_status="auth_required_rtsp", source_metadata={"media_type": "rtsp"}),
            CameraCandidate(stream_url="https://public.example/unknown.m3u8", validation_status="rtsp_validation_unavailable", source_metadata={"media_type": "hls"}),
        ],
        trusted_candidates=[],
        review_candidates=[],
    )
    assert dashboard["dead"] == 1
    assert dashboard["restricted"] == 1
    assert dashboard["not_validated"] == 1


def test_candidate_table_includes_all_dispositions_and_metadata(tmp_path, monkeypatch):
    import csv

    target = _target("California traffic cameras")
    target.intent.camera_type_intent = "traffic"
    candidates = [
        CameraCandidate("https://media.example/trusted.m3u8", lat=38, lon=-77, scope_status="in_scope", target_id=target.target_id, target_label=target.target_label, validation_status="active_live_verified", trust_level="trusted", source_metadata={"media_type": "hls", "currentImageURL": "https://media.example/trusted.jpg"}),
        CameraCandidate("https://media.example/review.m3u8", lat=38, lon=-77, scope_status="review", target_id=target.target_id, target_label=target.target_label, validation_status="active_live_unknown", trust_level="untrusted", source_metadata={"media_type": "hls"}),
        CameraCandidate("https://media.example/dead.m3u8", lat=38, lon=-77, scope_status="review", target_id=target.target_id, target_label=target.target_label, validation_status="dead", trust_level="rejected", source_metadata={"media_type": "hls"}),
        CameraCandidate("https://media.example/out.m3u8", lat=1, lon=1, scope_status="out_of_scope", target_id=target.target_id, target_label=target.target_label, validation_status="not_validated", trust_level="rejected", source_metadata={"media_type": "hls"}),
        CameraCandidate("https://media.example/unknown.m3u8", scope_status="unknown", target_id=target.target_id, target_label=target.target_label, validation_status="not_validated", trust_level="untrusted", source_metadata={"media_type": "hls"}),
    ]
    cs = CandidateSet(unique=candidates, review=candidates, rejected=[candidates[3]])
    pipeline = ReviewAndValidationPipeline(_cfg(tmp_path, profile=RuntimeProfile.FAST))
    _, outputs = pipeline.run([target], cs)

    rows = list(csv.DictReader((tmp_path / "camera_candidates_table.csv").open(encoding="utf-8", newline="")))
    assert outputs.camera_candidates_table_rows == len(candidates)
    assert len(rows) == len(candidates)
    assert {row["candidate_disposition"] for row in rows} >= {"trusted", "untrusted_review", "dead", "out_of_scope", "not_validated"}
    assert all(row["camera_type"] == "traffic" for row in rows)
    assert all(row["raw_camera_type"] == "" for row in rows)
    trusted = next(row for row in rows if row["stream_url"].endswith("trusted.m3u8"))
    assert trusted["snapshot_url"] == "https://media.example/trusted.jpg"
    assert trusted["thumbnail_url"] == "https://media.example/trusted.jpg"
    status = json.loads((tmp_path / "logs" / "camera_candidates_table_status.json").read_text(encoding="utf-8"))
    assert status["rows"] == len(candidates)
    assert status["includes_rejected_candidates"] is True


def test_run_summary_is_summary_only(tmp_path):
    state = __import__("camera_discovery.core.models", fromlist=["RunState"]).RunState(config=_cfg(tmp_path))
    state.candidates = CandidateSet(unique=[CameraCandidate(stream_url=f"https://media.example/{idx}.m3u8", source_metadata={"blob": "x" * 1000}) for idx in range(200)])
    data = state.to_dict()
    text = json.dumps(data)
    assert data["summary_only"] is True
    assert "blob" not in text
    assert len(text) < 50000


def test_full_hls_validation_checks_media_and_variant_playlists(tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b""
            status = 200
            if self.path == "/media.m3u8":
                body = b"#EXTM3U\n#EXTINF:2,\nseg.ts\n"
            elif self.path == "/variant.m3u8":
                body = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nmedia.m3u8\n"
            elif self.path == "/dead.m3u8":
                body = b"#EXTM3U\n#EXTINF:2,\nmissing.ts\n"
            elif self.path == "/seg.ts":
                body = b"segment"
            else:
                status = 404
                body = b"not found"
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def do_HEAD(self):
            if self.path == "/seg.ts":
                self.send_response(200)
            else:
                self.send_response(404)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        full = ReviewAndValidationPipeline(_cfg(tmp_path / "full", profile=RuntimeProfile.FULL))
        balanced = ReviewAndValidationPipeline(_cfg(tmp_path / "balanced", profile=RuntimeProfile.BALANCED))
        assert full._validate_hls(f"{base}/media.m3u8") == "active_live_verified"
        assert full._validate_hls(f"{base}/variant.m3u8") == "active_live_verified"
        assert full._validate_hls(f"{base}/dead.m3u8") == "active_playlist_dead_segments"
        assert balanced._validate_hls(f"{base}/media.m3u8") == "active_live_unknown"
    finally:
        server.shutdown()
