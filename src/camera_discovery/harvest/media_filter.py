from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable
from urllib.parse import urlparse, urlsplit, urlunsplit

from camera_discovery.core.models import HarvestedUrlRecord
from camera_discovery.extraction.media import _looks_like_non_camera_asset


SUPPORTED_MEDIA_TYPES = ("hls", "rtsp", "mjpeg", "image_snapshot", "video_file", "stream", "unknown_media")
SUPPORTED_MEDIA_CATEGORIES = {
    "all",
    "*",
    "hls",
    "mjpeg",
    "rtsp",
    "rtsps",
    "image",
    "snapshot",
    "image_snapshot",
    "video",
    "video_file",
    "stream",
    "unknown",
    "unknown_media",
}
SUPPORTED_EXTENSIONS = {".m3u8", ".mjpg", ".mjpeg", ".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".mov", ".m4v"}
IMAGE_ASSET_FILTER_MODES = {"raw", "exclude-page-assets", "camera-evidence"}
PAGE_ASSET_TERMS = {
    "favicon", "apple-touch-icon", "icon", "logo", "sprite", "badge", "avatar",
    "profile", "placeholder", "loading", "spinner", "banner", "hero",
    "background", "bg-", "open-graph", "og:image", "twitter:image", "social",
    "share", "site-logo", "tracking", "pixel", "1x1",
}
CAMERA_IMAGE_EVIDENCE_TERMS = {
    "camera", "cam", "cctv", "snapshot", "current", "reference", "trafficcam",
    "webcam", "cctvimage", "stream", "view",
}
CAMERA_IMAGE_ASSET_ROLES = {"current_image_snapshot", "reference_image_snapshot", "image_snapshot"}
CATEGORY_EXTENSIONS = {
    "hls": {".m3u8"},
    "rtsp": set(),
    "mjpeg": {".mjpg", ".mjpeg"},
    "image_snapshot": {".jpg", ".jpeg", ".png", ".webp"},
    "video_file": {".mp4", ".webm", ".mov", ".m4v"},
    "stream": set(),
    "unknown_media": set(),
}
JSON_ENDPOINT_HINT_RE = re.compile(r"(?:\.json(?:\?|$)|/api/|/feed|/feeds|/layer|/layers|/query|MapServer|FeatureServer|camera|cameras)", re.I)
URL_RE = re.compile(r"(?:https?|rtsps?)://[^\s'\"<>\\)\]}]+", re.I)
QUOTED_MEDIA_RE = re.compile(
    r"[\"']((?:rtsps?://[^\"']+)|[^\"']+\.(?:m3u8|mjpg|mjpeg|jpg|jpeg|png|webp|mp4|webm|mov|m4v)(?:\?[^\"']*)?)[\"']",
    re.I,
)
MEDIA_EXTENSION_RE = re.compile(r"\.(m3u8|mjpg|mjpeg|jpg|jpeg|png|webp|mp4|webm|mov|m4v)(?:$|[?#])", re.I)
JSON_MEDIA_KEYS = {
    "url",
    "src",
    "href",
    "stream",
    "streamurl",
    "stream_url",
    "streamingurl",
    "streaming_url",
    "hls",
    "hlsurl",
    "hls_url",
    "m3u8",
    "video",
    "videourl",
    "video_url",
    "media",
    "mediaurl",
    "media_url",
    "image",
    "imageurl",
    "image_url",
    "snapshot",
    "snapshoturl",
    "snapshot_url",
    "currentimage",
    "currentimageurl",
    "current_image_url",
    "mjpeg",
    "mjpegurl",
    "mjpeg_url",
}
JSON_METADATA_KEYS = {
    "id",
    "camera_id",
    "cameraid",
    "device_id",
    "deviceid",
    "name",
    "title",
    "label",
    "description",
    "location",
    "location_text",
    "intersection",
    "route",
    "road",
    "direction",
    "camera_direction",
    "facing",
    "bearing",
    "heading",
    "azimuth",
    "orientation",
    "latitude",
    "lat",
    "longitude",
    "lon",
    "lng",
    "x",
    "y",
    "coordinates",
    "geometry",
    "date",
    "time",
    "timestamp",
    "datetime",
    "recordepoch",
    "recorddatetime",
    "last_updated",
    "last_update",
    "last_refresh",
    "capture_time",
    "captured_at",
    "agency",
    "owner",
    "operator",
    "provider",
    "city",
    "county",
    "state",
    "country",
    "refresh_rate",
    "refresh_interval",
    "refresh_seconds",
    "update_interval",
}

LATITUDE_KEYS = {"lat", "latitude", "cameralat", "cameralatitude", "gpslat", "gpslatitude"}
LONGITUDE_KEYS = {"lon", "lng", "long", "longitude", "cameralon", "cameralng", "cameralongitude", "gpslon", "gpslng", "gpslongitude"}
# Use x/y only when they appear as a pair and plausibly represent lon/lat.
X_LONGITUDE_KEYS = {"x", "coordx", "mapx", "longitudex"}
Y_LATITUDE_KEYS = {"y", "coordy", "mapy", "latitudey"}
DIRECTION_KEYS = {"direction", "cameradirection", "facing", "facingdirection", "viewdirection", "lookdirection", "orientation"}
BEARING_KEYS = {"bearing", "camerabearing", "azimuth", "angle", "viewangle"}
HEADING_KEYS = {"heading", "cameraheading", "viewheading"}
DATE_KEYS = {"date", "recorddate", "capturedate", "imagedate", "snapshotdate", "lastupdatedate", "updatedate"}
TIME_KEYS = {"time", "recordtime", "capturetime", "imagetime", "snapshottime", "lastupdatetime", "updatetime"}
TIMESTAMP_KEYS = {
    "timestamp",
    "datetime",
    "recordepoch",
    "recorddatetime",
    "capturedat",
    "capturetimestamp",
    "imagetimestamp",
    "snapshottimestamp",
    "lastupdated",
    "lastupdate",
    "lastrefreshed",
    "lastrefresh",
    "updated",
    "updatetime",
    "updatetimestamp",
    "recordedat",
    "createdat",
    "observedat",
}


def normalize_key(key: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key).casefold())


class MediaFilter:
    def __init__(self, requested: list[str], categories: set[str], extensions: set[str], all_media: bool) -> None:
        self.requested = requested
        self.categories = categories
        self.extensions = extensions
        self.all_media = all_media

    def matches(self, record: HarvestedUrlRecord) -> bool:
        if self.all_media:
            return True
        ext = media_extension(record.url)
        return record.media_type in self.categories or (ext in self.extensions if ext else False)

def parse_media_filter(values: Iterable[str] | None) -> MediaFilter:
    tokens: list[str] = []
    for value in values or []:
        for part in str(value).split(","):
            cleaned = part.strip().casefold()
            if cleaned:
                tokens.append(cleaned)
    if not tokens or any(token in {"all", "*"} for token in tokens):
        return MediaFilter(requested=tokens or ["all"], categories=set(SUPPORTED_MEDIA_TYPES), extensions=set(SUPPORTED_EXTENSIONS), all_media=True)
    categories: set[str] = set()
    extensions: set[str] = set()
    invalid: list[str] = []
    for token in tokens:
        normalized = normalize_media_token(token)
        if normalized.startswith("."):
            if normalized not in SUPPORTED_EXTENSIONS:
                invalid.append(token)
            else:
                extensions.add(normalized)
            continue
        if normalized not in SUPPORTED_MEDIA_TYPES:
            invalid.append(token)
        else:
            categories.add(normalized)
            if normalized == "stream":
                categories.add("rtsp")
            extensions.update(CATEGORY_EXTENSIONS.get(normalized, set()))
    if invalid:
        examples = ".m3u8, .m3u8,mp4, hls, image,stream, video_file"
        allowed = ", ".join(sorted(SUPPORTED_MEDIA_CATEGORIES | {ext.lstrip(".") for ext in SUPPORTED_EXTENSIONS} | SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported --media value(s): {', '.join(invalid)}. Supported values include: {allowed}. Examples: {examples}")
    return MediaFilter(requested=tokens, categories=categories, extensions=extensions, all_media=False)

def normalize_media_token(token: str) -> str:
    token = token.strip().casefold()
    if not token:
        return "all"
    if token in {"all", "*"}:
        return "all"
    if token.startswith("."):
        return token
    if token in {"jpg", "jpeg", "png", "webp", "m3u8", "mjpg", "mjpeg", "mp4", "webm", "mov", "m4v"}:
        return "." + token
    if token == "image":
        return "image_snapshot"
    if token == "snapshot":
        return "image_snapshot"
    if token in {"rtsps"}:
        return "rtsp"
    if token == "video":
        return "video_file"
    if token == "unknown":
        return "unknown_media"
    return token

def classify_media_url(url: str, *, key_hint: str = "", content_type: str = "") -> str | None:
    if not url or not url.startswith(("http://", "https://", "rtsp://", "rtsps://")):
        return None
    lowered = url.casefold()
    if lowered.startswith(("rtsp://", "rtsps://")):
        return "rtsp"
    path = urlparse(url).path.casefold()
    ctype = content_type.casefold()
    if path.endswith(".m3u8") or ".m3u8" in lowered or "mpegurl" in ctype:
        return "hls"
    if path.endswith((".mjpg", ".mjpeg")) or "multipart/x-mixed-replace" in ctype:
        return "mjpeg"
    if path.endswith((".mp4", ".webm", ".mov", ".m4v")):
        return "video_file"
    if path.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "image_snapshot"
    if any(token in key_hint.casefold() for token in ("stream", "video", "media", "mjpeg", "rtsp")) and url.startswith(("http://", "https://", "rtsp://", "rtsps://")):
        return "stream"
    if any(token in lowered for token in ("/stream", "stream=", "/video", "video=", "/media", "media=")) and not MEDIA_EXTENSION_RE.search(url):
        return "stream"
    return None

def media_extension(url: str) -> str | None:
    path = urlparse(url).path.casefold()
    for ext in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if path.endswith(ext):
            return ext
    return None

def apply_image_asset_filter(records: list[HarvestedUrlRecord], mode: str) -> tuple[list[HarvestedUrlRecord], dict[str, Any]]:
    normalized = (mode or "raw").strip().casefold()
    if normalized not in IMAGE_ASSET_FILTER_MODES:
        allowed = ", ".join(sorted(IMAGE_ASSET_FILTER_MODES))
        raise ValueError(f"Invalid image asset filter {mode!r}; expected one of: {allowed}")
    removed_by_reason: Counter[str] = Counter()
    kept: list[HarvestedUrlRecord] = []
    for record in records:
        keep, reason = image_asset_filter_decision(record, normalized)
        if keep:
            kept.append(record)
        else:
            removed_by_reason[reason or "image_asset_filter"] += 1
    return kept, {
        "image_asset_filter": normalized,
        "pre_image_filter_records": len(records),
        "post_image_filter_records": len(kept),
        "kept": len(kept),
        "removed": len(records) - len(kept),
        "removed_by_reason": dict(removed_by_reason),
    }

def image_asset_filter_decision(record: HarvestedUrlRecord, mode: str) -> tuple[bool, str | None]:
    if mode == "raw" or record.media_type != "image_snapshot":
        return True, None
    if mode == "exclude-page-assets":
        if has_page_asset_evidence(record):
            return False, "page_asset_evidence"
        return True, None
    if mode == "camera-evidence":
        if has_camera_image_evidence(record):
            return True, None
        return False, "missing_camera_image_evidence"
    return True, None

def has_page_asset_evidence(record: HarvestedUrlRecord) -> bool:
    haystack = image_record_text(record)
    if _looks_like_non_camera_asset(record.url):
        return True
    return any(term in haystack for term in PAGE_ASSET_TERMS)

def has_camera_image_evidence(record: HarvestedUrlRecord) -> bool:
    if record.asset_role in CAMERA_IMAGE_ASSET_ROLES and record.camera_record_id:
        return True
    if normalize_key(record.asset_field or "") in {"currentimageurl", "referenceimageurl", "imageurl", "snapshoturl", "cameraimageurl"}:
        return True
    if record.camera_record_id and (record.camera_id or record.lat is not None or record.lon is not None or record.in_service is not None or record.current_image_update_frequency is not None or record.reference_image_update_frequency is not None):
        return True
    metadata = record.metadata or {}
    metadata_keys = {normalize_key(k) for k in metadata}
    if metadata_keys & {"imagedescription", "currentimageupdatefrequency", "referenceimageupdatefrequency", "refreshrate", "refreshinterval", "cameraid", "camera_id", "inservice", "direction", "lat", "latitude", "lon", "longitude", "route", "intersection"}:
        return True
    haystack = image_record_core_text(record)
    return any(term in haystack for term in CAMERA_IMAGE_EVIDENCE_TERMS)

def image_record_core_text(record: HarvestedUrlRecord) -> str:
    parts = [
        record.url, record.title, record.description, record.location_text, record.camera_id,
        record.asset_role, record.asset_field, record.field_path, record.discovery_method,
    ]
    return " ".join(str(part or "") for part in parts).casefold()

def image_record_text(record: HarvestedUrlRecord) -> str:
    metadata = record.metadata or {}
    parts = [
        record.url, record.title, record.description, record.location_text, record.camera_id,
        record.asset_role, record.asset_field, record.field_path, record.discovery_method,
    ]
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            parts.extend([str(key), str(value)])
    return " ".join(str(part or "") for part in parts).casefold()

def canonical_media_url(url: str) -> str:
    cleaned = _strip_extraction_trailers(url)
    split = urlsplit(cleaned)
    scheme = split.scheme.casefold()
    host = (split.hostname or "").casefold()
    port = split.port
    if not scheme and split.netloc:
        # Scheme-relative media URLs are common in JSON payloads after unescaping
        # strings such as \/\/media.example\/cam.m3u8. Normalize them to https
        # before writing artifacts so downstream files contain directly usable URLs.
        scheme = "https"
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        host = f"{host}:{port}"
    netloc = host
    if split.username:
        auth = split.username
        if split.password:
            auth = f"{auth}:{split.password}"
        netloc = f"{auth}@{host}"
    return urlunsplit((scheme, netloc, split.path, split.query, ""))


def _strip_extraction_trailers(url: str) -> str:
    value = str(url or "").strip()
    # Text/JSON/HTML extraction often leaves escape characters or closing punctuation
    # immediately after the URL. Keep query tokens intact, but trim unambiguous
    # delimiters that cannot be part of a usable media URL.
    value = _decode_json_url_escapes(value)
    trailing = "\\\'\"),;}]"
    while value and value[-1] in trailing:
        value = value[:-1].rstrip()
    return _prefer_embedded_absolute_media_url(value)


def _decode_json_url_escapes(value: str) -> str:
    return (
        value.replace(r"\/", "/")
        .replace(r"\u002F", "/")
        .replace(r"\u002f", "/")
    )


def _prefer_embedded_absolute_media_url(value: str) -> str:
    # Some feeds expose a scheme-relative media URL as an escaped JSON string,
    # and extraction can accidentally join it to the endpoint path, e.g.
    # https://source.example/path/\/\/media.example\/cam.m3u8. If a media URL
    # contains an embedded scheme-relative absolute URL, prefer the embedded
    # URL rather than writing two URLs strung together as one artifact entry.
    default_scheme = urlsplit(value).scheme.casefold() or "https"
    for match in re.finditer(r"(?<!:)//([A-Za-z0-9.-]+\.[A-Za-z]{2,})(/[^\s'\"<>]*)", value):
        candidate = f"{default_scheme}://{match.group(1)}{match.group(2)}"
        if MEDIA_EXTENSION_RE.search(candidate):
            return candidate
    return value
