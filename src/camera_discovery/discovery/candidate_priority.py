from __future__ import annotations

from collections import Counter
from typing import Iterable

from camera_discovery.core.models import CameraCandidate, CandidateSet

FIRST_CLASS_MEDIA_TYPES = {"hls", "hls_stream", "image_snapshot"}

PRIORITY_BUCKET_LABELS = {
    0: "located_in_scope_direct_media",
    1: "located_review_direct_media",
    2: "located_unknown_direct_media",
    3: "unlocated_direct_media",
    4: "structured_unlocated_camera_record",
    5: "located_out_of_scope",
    6: "weak_or_asset_candidate",
}


def candidate_media_type(candidate: CameraCandidate) -> str:
    """Return the normalized media type used by candidate-priority decisions."""
    metadata = candidate.source_metadata or {}
    media_type = str(metadata.get("media_type") or "").strip().casefold()
    lower_url = (candidate.stream_url or "").casefold()
    if not media_type:
        if ".m3u8" in lower_url:
            media_type = "hls"
        elif lower_url.split("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp")):
            media_type = "image_snapshot"
    if media_type == "image":
        return "image_snapshot"
    if media_type == "video":
        return "video_file"
    return media_type or "unknown"


def is_first_class_direct_media(candidate: CameraCandidate) -> bool:
    """Return True for normal-run media types that can be validated as camera candidates."""
    media_type = candidate_media_type(candidate)
    if media_type in FIRST_CLASS_MEDIA_TYPES:
        return True
    return ".m3u8" in (candidate.stream_url or "").casefold()


def is_structured_camera_like(candidate: CameraCandidate) -> bool:
    """Return True when metadata suggests a structured camera record, even if unlocated."""
    metadata = candidate.source_metadata or {}
    camera_keys = {
        "camera_id",
        "camera_name",
        "camera_type",
        "json_record_path",
        "json_record_schema_hint",
        "json_endpoint_url",
        "raw_camera_type",
    }
    if any(metadata.get(key) not in (None, "", [], {}) for key in camera_keys):
        return True
    method = (candidate.discovery_method or "").casefold()
    return method in {"structured_json", "json_endpoint", "linked_endpoint", "harvest_handoff"}


def candidate_priority_bucket(candidate: CameraCandidate) -> int:
    """Return a deterministic priority bucket for validation/review ordering.

    Lower values sort first. Coordinates make candidates easier to validate and
    review quickly, but this helper does not modify trust. Existing validation,
    scope, and output gates remain authoritative.
    """
    scope = (candidate.scope_status or "unknown").casefold()
    has_coords = candidate.has_coordinates
    direct_media = is_first_class_direct_media(candidate)
    if scope == "out_of_scope" and has_coords:
        return 5
    if has_coords and direct_media:
        if scope == "in_scope":
            return 0
        if scope == "review":
            return 1
        return 2
    if direct_media and scope != "out_of_scope":
        return 3
    if is_structured_camera_like(candidate) and scope != "out_of_scope":
        return 4
    if scope == "out_of_scope":
        return 5
    return 6


def candidate_priority_label(candidate: CameraCandidate) -> str:
    return PRIORITY_BUCKET_LABELS[candidate_priority_bucket(candidate)]


def candidate_priority_sort_key(candidate: CameraCandidate) -> tuple[int, int]:
    """Stable sort key for candidate priority.

    Lower priority buckets still dominate. Passive evidence is only a secondary
    prioritization signal inside the existing bucket; it never modifies scope,
    validation, or trust.
    """
    metadata = candidate.source_metadata or {}
    try:
        evidence_score = int(metadata.get("camera_evidence_score") or 0)
    except (TypeError, ValueError):
        evidence_score = 0
    return (candidate_priority_bucket(candidate), -evidence_score)


def prioritize_candidates(candidates: Iterable[CameraCandidate]) -> list[CameraCandidate]:
    return sorted(list(candidates), key=candidate_priority_sort_key)


def prioritize_candidate_set(candidate_set: CandidateSet) -> CandidateSet:
    """Return a shallow CandidateSet copy with all candidate lists priority-ordered."""
    unique = prioritize_candidates(candidate_set.unique)
    raw = list(candidate_set.raw)
    return CandidateSet(
        raw=raw,
        unique=unique,
        coordinate_bearing=prioritize_candidates(c for c in unique if c.has_coordinates),
        in_scope=prioritize_candidates(c for c in unique if c.scope_status == "in_scope"),
        review=prioritize_candidates(c for c in unique if c.scope_status in {"review", "unknown", "in_scope"}),
        rejected=prioritize_candidates(c for c in unique if c.scope_status == "out_of_scope"),
    )


def priority_bucket_counts(candidates: Iterable[CameraCandidate]) -> dict[str, int]:
    counter = Counter(candidate_priority_label(candidate) for candidate in candidates)
    return {label: counter.get(label, 0) for _, label in sorted(PRIORITY_BUCKET_LABELS.items()) if counter.get(label, 0)}
