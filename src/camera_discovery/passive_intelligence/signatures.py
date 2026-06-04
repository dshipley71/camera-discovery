from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

# Passive signatures are matched only against evidence already discovered by the
# pipeline. They must never be used to generate URLs or probe hosts.
SIGNATURES: tuple[dict[str, str], ...] = (
    {"family": "camera_path_fragment", "name": "axis_cgi_path", "value": "/axis-cgi/", "confidence": "moderate"},
    {"family": "mjpeg_path_fragment", "name": "mjpg_path", "value": "/mjpg/", "confidence": "moderate"},
    {"family": "mjpeg_path_fragment", "name": "mjpeg_path", "value": "/mjpeg/", "confidence": "moderate"},
    {"family": "snapshot_path_fragment", "name": "snapshot_path", "value": "/snapshot", "confidence": "moderate"},
    {"family": "snapshot_path_fragment", "name": "snap_jpg", "value": "/snap.jpg", "confidence": "moderate"},
    {"family": "snapshot_path_fragment", "name": "image_jpg", "value": "/image.jpg", "confidence": "low"},
    {"family": "camera_path_fragment", "name": "video_path", "value": "/video", "confidence": "low"},
    {"family": "camera_path_fragment", "name": "stream_path", "value": "/stream", "confidence": "low"},
    {"family": "camera_path_fragment", "name": "live_path", "value": "/live", "confidence": "low"},
    {"family": "hls_path_fragment", "name": "hls_path", "value": "/hls", "confidence": "moderate"},
    {"family": "playlist_extension", "name": "playlist_m3u8", "value": "/playlist.m3u8", "confidence": "high"},
    {"family": "playlist_extension", "name": "master_m3u8", "value": "/master.m3u8", "confidence": "high"},
    {"family": "camera_path_fragment", "name": "streaming_channels", "value": "/Streaming/Channels/", "confidence": "moderate"},
    {"family": "camera_path_fragment", "name": "isapi_path", "value": "/ISAPI/", "confidence": "moderate"},
    {"family": "onvif_reference", "name": "onvif_reference", "value": "/onvif/", "confidence": "moderate"},
    {"family": "camera_path_fragment", "name": "realmonitor_path", "value": "/cam/realmonitor", "confidence": "moderate"},
    {"family": "structured_endpoint_hint", "name": "mapserver", "value": "MapServer", "confidence": "moderate"},
    {"family": "structured_endpoint_hint", "name": "featureserver", "value": "FeatureServer", "confidence": "moderate"},
    {"family": "structured_endpoint_hint", "name": "geojson", "value": ".geojson", "confidence": "moderate"},
    {"family": "media_extension", "name": "m3u8_extension", "value": ".m3u8", "confidence": "high"},
    {"family": "media_extension", "name": "mpd_extension", "value": ".mpd", "confidence": "medium"},
    {"family": "media_extension", "name": "jpg_extension", "value": ".jpg", "confidence": "low"},
    {"family": "media_extension", "name": "jpeg_extension", "value": ".jpeg", "confidence": "low"},
    {"family": "media_extension", "name": "png_extension", "value": ".png", "confidence": "low"},
    {"family": "media_extension", "name": "webp_extension", "value": ".webp", "confidence": "low"},
)

VENDOR_HINTS = {
    "axis": "axis_vendor_hint",
    "hikvision": "hikvision_vendor_hint",
    "dahua": "dahua_vendor_hint",
    "mobotix": "mobotix_vendor_hint",
    "bosch": "bosch_vendor_hint",
    "sony": "sony_vendor_hint",
    "panasonic": "panasonic_vendor_hint",
}

DANGEROUS_SIGNATURE_TOKENS = re.compile(r"password|passwd|credential|username|login|exploit|cve-|vulnerab|bruteforce|brute_force", re.I)


def match_signatures(*values: Any) -> list[dict[str, str]]:
    """Match safe passive signatures against already-discovered strings."""
    haystacks: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, dict):
            haystacks.extend(_flatten_dict(value))
        elif isinstance(value, (list, tuple, set)):
            haystacks.extend(str(item) for item in value if item not in (None, ""))
        else:
            haystacks.append(str(value))
    text = "\n".join(haystacks)
    lowered = text.casefold()
    matches: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for signature in SIGNATURES:
        value = signature["value"]
        if DANGEROUS_SIGNATURE_TOKENS.search(value):
            continue
        if value.casefold() not in lowered:
            continue
        key = (signature["family"], signature["name"], value)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            {
                "signature_family": signature["family"],
                "signature_name": signature["name"],
                "matched_value": value,
                "confidence": signature["confidence"],
                "reason": f"Already-discovered evidence contains safe {signature['family']} signature {value}",
            }
        )
    vendor_text = _vendor_haystack(text)
    for vendor, name in VENDOR_HINTS.items():
        if vendor in vendor_text:
            key = ("vendor_hint", name, vendor)
            if key not in seen:
                seen.add(key)
                matches.append(
                    {
                        "signature_family": "vendor_hint",
                        "signature_name": name,
                        "matched_value": vendor,
                        "confidence": "low",
                        "reason": "Already-discovered evidence contains a generic camera-vendor hint",
                    }
                )
    return matches


def signature_family_counts(matches: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        family = str(match.get("signature_family") or "unknown")
        counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items()))


def _flatten_dict(value: dict[Any, Any]) -> list[str]:
    out: list[str] = []
    for key, item in value.items():
        if item in (None, "", [], {}):
            continue
        out.append(str(key))
        if isinstance(item, dict):
            out.extend(_flatten_dict(item))
        elif isinstance(item, (list, tuple, set)):
            out.extend(str(child) for child in item if child not in (None, ""))
        else:
            out.append(str(item))
    return out


def _vendor_haystack(text: str) -> str:
    parts: list[str] = []
    for raw in text.splitlines():
        try:
            split = urlsplit(raw.strip())
            if split.netloc or split.path:
                parts.append((split.netloc + " " + split.path).casefold())
        except Exception:
            continue
    parts.append(text.casefold())
    return "\n".join(parts)
