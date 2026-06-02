from __future__ import annotations

from typing import Any


def classify_protocol(url: str | None, *, content_type: str | None = None, metadata: dict[str, Any] | None = None, text: str | None = None) -> dict[str, Any]:
    """Classify protocol/media family from already-discovered evidence only."""
    metadata = metadata or {}
    explicit = str(metadata.get("media_type") or metadata.get("protocol_label") or "").casefold().strip()
    lowered_url = str(url or metadata.get("media_url") or metadata.get("stream_url") or "").casefold()
    lowered_ct = str(content_type or metadata.get("content_type") or "").casefold()
    sample = str(text or "")[:4096].casefold()
    reasons: list[str] = []

    def result(label: str, family: str, confidence: str, reason: str) -> dict[str, Any]:
        reasons.append(reason)
        return {
            "protocol_label": label,
            "media_family": family,
            "protocol_confidence": confidence,
            "protocol_reasons": _dedupe(reasons),
        }

    if explicit in {"hls", "hls_stream"}:
        return result("hls", "stream", "high", "metadata explicitly labels candidate as HLS")
    if explicit in {"rtsp", "rtsps", "rtsp_stream"}:
        return result("rtsp", "stream", "high", "metadata explicitly labels candidate as RTSP")
    if explicit in {"mjpeg", "mjpg"}:
        return result("mjpeg", "stream", "high", "metadata explicitly labels candidate as MJPEG")
    if explicit in {"image", "snapshot", "image_snapshot"}:
        return result("image_snapshot", "image", "high", "metadata explicitly labels candidate as an image snapshot")
    if explicit in {"dash", "mpd"}:
        return result("dash", "playlist", "high", "metadata explicitly labels candidate as DASH")
    if explicit in {"webrtc", "rtmp", "srt", "mp4"}:
        family = "stream" if explicit != "mp4" else "video_file"
        return result(explicit, family, "medium", f"metadata explicitly labels candidate as {explicit}")

    if lowered_url.startswith(("rtsp://", "rtsps://")):
        return result("rtsp", "stream", "high", "URL scheme is RTSP/RSTPS")
    if lowered_url.startswith("rtmp://"):
        return result("rtmp", "stream", "high", "URL scheme is RTMP")
    if lowered_url.startswith("srt://"):
        return result("srt", "stream", "high", "URL scheme is SRT")
    if ".m3u8" in lowered_url or "application/vnd.apple.mpegurl" in lowered_ct or "application/x-mpegurl" in lowered_ct or "#extm3u" in sample:
        return result("hls", "stream", "high", "URL/content indicates HLS playlist")
    if ".mpd" in lowered_url or "dash+xml" in lowered_ct:
        return result("dash", "playlist", "high", "URL/content indicates DASH manifest")
    if "multipart/x-mixed-replace" in lowered_ct or "multipart" in lowered_ct and "boundary" in lowered_ct:
        return result("mjpeg", "stream", "high", "content type indicates multipart MJPEG")
    if any(token in lowered_url for token in ("webrtc", "rtcpeerconnection", "whep")) or any(token in sample for token in ("rtcpeerconnection", "webrtc", "whep")):
        return result("webrtc", "stream", "medium", "already-discovered page/config contains WebRTC indicators")
    clean_path = lowered_url.split("?", 1)[0]
    if clean_path.endswith((".jpg", ".jpeg", ".png", ".webp")) or lowered_ct.startswith("image/"):
        return result("image_snapshot", "image", "medium", "URL/content type indicates image snapshot candidate")
    if clean_path.endswith(".mp4") or "video/mp4" in lowered_ct:
        return result("mp4", "video_file", "medium", "URL/content type indicates MP4 video file")
    if any(token in lowered_url for token in ("/stream", "/live", "/video", "/mjpg", "/mjpeg")):
        return result("unknown_stream", "stream", "low", "URL path looks media-like but protocol is not confirmed")
    if any(token in lowered_ct for token in ("json", "geojson")):
        return result("unknown", "structured_data", "low", "content type indicates structured data rather than direct media")
    if "html" in lowered_ct:
        return result("unknown", "page", "low", "content type indicates HTML page")
    return result("unknown", "unknown", "low", "no passive protocol evidence found")


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out
