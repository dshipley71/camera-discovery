from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from camera_discovery.core.models import CameraCandidate


M3U8_RE = re.compile(r"https?://[^\s'\"<>]+?\.m3u8(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.m3u8(?:\?[^'\"]*)?)['\"]", re.I)
IMAGE_RE = re.compile(r"https?://[^\s'\"<>]+?\.(?:jpg|jpeg|png|webp)(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.(?:jpg|jpeg|png|webp)(?:\?[^'\"]*)?)['\"]", re.I)
COORD_RE = re.compile(r"(?<!\d)([-+]?\d{1,2}\.\d{3,})\s*,\s*([-+]?\d{1,3}\.\d{3,})(?!\d)")
JSON_FEED_HINT_RE = re.compile(r"(?:\.json(?:\?|$)|/api/|/feed|/feeds|/layer|/layers|camera|cameras|mapserver|featureserver)", re.I)
MAP_LAYER_API_RE = re.compile(r"(?:/MapServer|/FeatureServer|/arcgis/|/api/cameras)", re.I)
DYNAMIC_PAGE_HINT_RE = re.compile(
    r"(?:__NEXT_DATA__|__NUXT__|window\.__INITIAL_STATE__|leaflet|mapbox|openlayers|video\.js|hls\.js|jwplayer|clappr|arcgis|MapServer|FeatureServer|camera|cameras|webcam|webcams|cctv|live|snapshot)",
    re.I,
)
MAX_WORKERS = 8


def _candidate_media_type(candidate: CameraCandidate) -> str:
    media_type = str((candidate.source_metadata or {}).get("media_type") or "").casefold()
    if media_type:
        return media_type
    if _looks_like_hls(candidate.stream_url):
        return "hls"
    return "image_snapshot"

def _looks_like_non_camera_asset(url: str) -> bool:
    lower = url.casefold()
    asset_markers = (
        "og-default", "open_graph", "opengraph", "favicon", "logo", "sprite", "placeholder",
        "avatar", "basemap", "/dark_all/", "/light_all/", "/tile/", "/tiles/", "cartocdn.com",
        "openstreetmap.org/", "leaflet", "mapbox", "googleapis.com", "gstatic.com",
        "apple-touch-icon", "mstile", "mask-icon", "site-icon", "site_icon", "seal_", "/seal",
        "/assets/", "/static/", "/template", "/templates/", "/banner", "/banners/",
        "/icons/", "/icon/", "/images/icons/", "retail", "store-logo", "store_logo",
    )
    if any(marker in lower for marker in asset_markers):
        return True
    if _looks_like_thumbnail_asset(url):
        return True
    path = urlparse(url).path.casefold()
    name = path.rsplit("/", 1)[-1]
    if name in {"default.png", "default.jpg", "blank.png", "blank.jpg", "loading.gif"}:
        return True
    return False

def _looks_like_thumbnail_asset(url: str) -> bool:
    """Return True for preview thumbnails that should not become camera streams.

    Camera directories often include preview images, retail/service thumbnails,
    OpenGraph thumbnails, and CDN/object-store thumbnails. Those may be useful
    as metadata when attached to an already-discovered camera, but they are not
    refreshable camera snapshot endpoints and should not consume image-snapshot
    candidate budget.
    """
    path = unquote(urlparse(url).path).casefold()
    segments = [part for part in path.split("/") if part]
    if any(part in {"thumb", "thumbs", "thumbnail", "thumbnails"} for part in segments):
        return True
    thumbnail_markers = (
        "/services/thumb/", "/services/thumbs/", "/service/thumb/", "/service/thumbnail/",
        "/preview/thumb/", "/previews/thumb/", "/cdn/thumb/", "/cdn-cgi/image/",
    )
    if any(marker in path for marker in thumbnail_markers):
        return True
    name = segments[-1] if segments else ""
    if re.search(r"(?:^|[-_])(thumb|thumbnail|preview)(?:[-_]|$)", name):
        return True
    return False

def _camera_id_from_url(url: str) -> str | None:
    parts = [unquote(part).strip() for part in urlparse(url).path.split("/") if part.strip()]
    if not parts:
        return None
    stem = parts[-1].split(".", 1)[0].strip()
    if stem.casefold() == "playlist" and len(parts) >= 2:
        stem = parts[-2].split(".", 1)[0].strip()
    return stem or None

def _humanize_camera_slug_from_url(url: str) -> str | None:
    stem = (_camera_id_from_url(url) or "").casefold()
    if not stem or len(stem) < 4:
        return None
    if _looks_like_non_camera_asset(url):
        return None
    text = re.sub(r"[_\-]+", " ", stem)
    # Compact highway identifiers such as sr99/us101/i80 are common in camera image paths.
    text = re.sub(r"sr(\d{1,3})(\d+(?:st|nd|rd|th))", r"SR \1 \2", text)
    text = re.sub(r"\bsr\s*(\d+)", r"SR \1 ", text)
    text = re.sub(r"\bus\s*(\d+)", r"US \1 ", text)
    text = re.sub(r"\bi\s*(\d+)", r"I-\1 ", text)
    text = re.sub(r"\b(nb|sb|eb|wb)\b", lambda m: m.group(1).upper(), text)
    text = re.sub(r"(?<=\d)(nb|sb|eb|wb)", lambda m: " " + m.group(1).upper() + " ", text)
    text = re.sub(r"(\d+)(st|nd|rd|th)", r"\1\2 ", text)
    text = re.sub(r"\bst\b", "St", text)
    text = re.sub(r"\brd\b", "Rd", text)
    text = re.sub(r"\bave\b", "Ave", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not any(re.search(pattern, text, re.I) for pattern in (r"\b(?:I-|SR|US)\s*\d+\b", r"\b\d+(?:st|nd|rd|th)\b", r"\b(?:NB|SB|EB|WB)\b", r"\b(?:St|Rd|Ave)\b")):
        return None
    return text[:120]

def _looks_like_image(url: str) -> bool:
    return bool(re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", url, re.I))

def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out

def _dedupe_media_urls(values: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for url, media_type in values:
        key = url.split("#", 1)[0]
        if key not in seen:
            seen.add(key)
            out.append((key, media_type))
    return out

def _looks_like_hls(url: str) -> bool:
    return url.lower().split("?", 1)[0].endswith(".m3u8")

def _float_or_none(value):
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None

def _int_or_none(value):
    try:
        return None if value in (None, "") else int(value)
    except (TypeError, ValueError):
        return None

def _chunks(values: list[CameraCandidate], size: int) -> list[list[CameraCandidate]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
