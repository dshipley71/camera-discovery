from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable

from camera_discovery.passive_intelligence.protocol_labels import classify_protocol
from camera_discovery.passive_intelligence.signatures import match_signatures, signature_family_counts
from camera_discovery.passive_intelligence.http_metadata import redact_sensitive_url

CAMERA_TERMS = (
    "camera",
    "cameras",
    "webcam",
    "webcams",
    "cctv",
    "traffic cam",
    "weather cam",
    "snapshot",
    "stream",
    "live cam",
    "livestream",
)

STRUCTURED_HINTS = ("json", "geojson", "mapserver", "featureserver", "arcgis", "camera_id", "route", "direction", "status", "latitude", "longitude")
LIVE_STATUSES = {"active_live_unknown", "active_live_verified", "active_image_snapshot_refreshing", "active_rtsp_verified"}
DEAD_FRAGMENTS = ("dead", "offline", "invalid", "decode_failed", "static_image_asset", "not_image", "dead_segments")
RESTRICTED_FRAGMENTS = ("restricted", "auth_required", "unauthorized", "forbidden", "401", "403")


def evidence_band(score: int) -> str:
    if score <= 0:
        return "none"
    if score < 25:
        return "weak"
    if score < 50:
        return "moderate"
    if score < 75:
        return "strong"
    return "very_strong"


def enrich_source_row_with_passive_intelligence(row: dict[str, Any], source_policy: Any | None = None) -> dict[str, Any]:
    score, reasons, signals, matches = score_source_row(row, source_policy=source_policy)
    row["source_camera_evidence_score"] = score
    row["source_camera_evidence_band"] = evidence_band(score)
    row["source_camera_evidence_reasons"] = reasons
    row["source_camera_evidence_signals"] = signals
    row["source_signature_matches"] = matches[:12]
    row["why_source_mattered"] = why_it_mattered(reasons, prefix="Source")
    return row


def enrich_candidate_with_passive_intelligence(candidate: Any, source_policy: Any | None = None) -> Any:
    metadata = getattr(candidate, "source_metadata", None) or {}
    score, reasons, signals, matches, protocol = score_candidate(candidate, source_policy=source_policy)
    metadata["camera_evidence_score"] = score
    metadata["camera_evidence_band"] = evidence_band(score)
    metadata["camera_evidence_reasons"] = reasons
    metadata["camera_evidence_signals"] = signals
    metadata["signature_matches"] = matches[:12]
    metadata["protocol_label"] = protocol["protocol_label"]
    metadata["media_family"] = protocol["media_family"]
    metadata["protocol_confidence"] = protocol["protocol_confidence"]
    metadata["protocol_reasons"] = protocol["protocol_reasons"]
    metadata["why_candidate_mattered"] = why_it_mattered(reasons, prefix="Candidate")
    setattr(candidate, "source_metadata", metadata)
    reasons_list = getattr(candidate, "reasons", None)
    if isinstance(reasons_list, list):
        for reason in reasons[:3]:
            token = f"passive_intelligence:{reason}"
            if token not in reasons_list:
                reasons_list.append(token)
    return candidate


def score_source_row(row: dict[str, Any], source_policy: Any | None = None) -> tuple[int, list[str], dict[str, Any], list[dict[str, Any]]]:
    url = str(row.get("url") or "")
    title = str(row.get("title") or row.get("source_name") or "")
    snippet = str(row.get("snippet") or row.get("body") or row.get("source_notes") or "")
    http_metadata = row.get("http_metadata") if isinstance(row.get("http_metadata"), dict) else {}
    content_type = str(http_metadata.get("content_type") or row.get("content_type") or "")
    matches = match_signatures(url, title, snippet, http_metadata)
    reasons: list[str] = []
    signals: dict[str, Any] = {}
    score = 0
    text = f"{url} {title} {snippet}".casefold()

    blocked_reason = None
    if source_policy is not None:
        try:
            blocked_reason = source_policy.block_reason(url)
        except Exception:
            blocked_reason = None
    if blocked_reason:
        score -= 30
        reasons.append("blocked source policy match")
        signals["blocked_reason"] = blocked_reason
    elif url:
        score += 10
        reasons.append("source URL passed blocked-source policy check")
        signals["source_policy_allowed"] = True

    camera_terms = [term for term in CAMERA_TERMS if term in text]
    if camera_terms:
        add = min(20, 8 + len(camera_terms) * 3)
        score += add
        reasons.append("source title/snippet/URL contains camera or live-media terms")
        signals["camera_terms"] = camera_terms[:8]

    if any(hint in text or hint in content_type.casefold() for hint in STRUCTURED_HINTS):
        score += 15
        reasons.append("source has structured camera endpoint hints")
        signals["structured_endpoint_hint"] = True

    protocol = classify_protocol(url, content_type=content_type, metadata=row)
    signals["protocol_label"] = protocol["protocol_label"]
    if protocol["protocol_label"] in {"hls", "rtsp", "mjpeg", "image_snapshot", "dash", "webrtc", "rtmp", "srt"}:
        score += 20
        reasons.append("source URL/content has direct media protocol evidence")

    if matches:
        signature_score = min(20, sum(_signature_weight(match) for match in matches))
        score += signature_score
        reasons.append("source matched safe passive camera/media signatures")
        signals["signature_family_counts"] = signature_family_counts(matches)

    if row.get("source_provider") in {"directory", "direct"}:
        score += 8
        reasons.append("source came from configured directory/direct source")
    if row.get("source_provider") == "asset_host_promotion":
        score += 8
        reasons.append("source came from repeated camera asset-host promotion")
    if http_metadata.get("http_status") and int(http_metadata.get("http_status") or 0) < 400:
        score += 5
        reasons.append("source HTTP fetch returned a reachable status")
    if http_metadata.get("www_authenticate_present"):
        score -= 20
        reasons.append("source advertised authentication requirement")

    score = max(0, min(100, score))
    return score, _dedupe(reasons), signals, matches


def score_candidate(candidate: Any, source_policy: Any | None = None) -> tuple[int, list[str], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    metadata = getattr(candidate, "source_metadata", None) or {}
    url = str(getattr(candidate, "stream_url", "") or metadata.get("media_url") or "")
    source_url = str(getattr(candidate, "source_url", "") or "")
    title = str(getattr(candidate, "title", "") or metadata.get("camera_name") or metadata.get("source_name") or "")
    location = str(getattr(candidate, "location_text", "") or metadata.get("location_display") or metadata.get("location_text") or "")
    http_metadata = metadata.get("http_metadata") if isinstance(metadata.get("http_metadata"), dict) else {}
    protocol = classify_protocol(url, content_type=http_metadata.get("content_type") or metadata.get("content_type"), metadata=metadata)
    matches = match_signatures(url, source_url, title, location, metadata, http_metadata)
    reasons: list[str] = []
    signals: dict[str, Any] = {"protocol_label": protocol["protocol_label"], "media_family": protocol["media_family"]}
    score = 0

    blocked_reason = None
    if source_policy is not None:
        try:
            blocked_reason = source_policy.block_reason(url) or source_policy.block_reason(source_url)
        except Exception:
            blocked_reason = None
    if blocked_reason:
        score -= 30
        reasons.append("candidate matched blocked-source policy")
        signals["blocked_reason"] = blocked_reason

    if protocol["protocol_label"] in {"hls", "rtsp", "mjpeg", "image_snapshot"}:
        score += 35
        reasons.append(f"direct {protocol['protocol_label']} media evidence")
    elif protocol["protocol_label"] in {"dash", "webrtc", "rtmp", "srt", "mp4"}:
        score += 25
        reasons.append(f"direct {protocol['protocol_label']} media evidence")
    elif protocol["protocol_label"] == "unknown_stream":
        score += 10
        reasons.append("URL has stream-like path but protocol is unconfirmed")

    structured_keys = [key for key in ("json_endpoint_url", "json_record_path", "json_record_schema_hint", "json_metadata_extracted") if metadata.get(key) not in (None, "", [], {})]
    if structured_keys:
        score += 30
        reasons.append("candidate came from structured camera metadata")
        signals["structured_metadata_keys"] = structured_keys

    camera_keys = [key for key in ("camera_id", "camera_name", "route", "road", "direction", "camera_status", "agency", "owner") if metadata.get(key) not in (None, "", [], {})]
    if camera_keys:
        score += min(20, 5 + 4 * len(camera_keys))
        reasons.append("candidate has camera identity/location/status fields")
        signals["camera_metadata_keys"] = camera_keys

    if bool(getattr(candidate, "has_coordinates", False)):
        score += 20
        reasons.append("candidate has source-extracted or geocoded coordinates")
        signals["has_coordinates"] = True

    source_score = _int_value(metadata.get("source_camera_evidence_score") or metadata.get("source_evidence_score"))
    if source_score:
        score += min(15, source_score // 5)
        reasons.append("candidate inherited evidence from its source row")
        signals["source_camera_evidence_score"] = source_score

    if matches:
        score += min(15, sum(_signature_weight(match) for match in matches))
        reasons.append("candidate matched safe passive camera/media signatures")
        signals["signature_family_counts"] = signature_family_counts(matches)

    scope_status = str(getattr(candidate, "scope_status", "") or "").casefold()
    if scope_status == "in_scope":
        score += 10
        reasons.append("candidate passed target scope check")
    elif scope_status == "out_of_scope":
        score -= 20
        reasons.append("candidate is out of target scope")

    validation_status = str(getattr(candidate, "validation_status", "") or metadata.get("validation_status") or "").casefold()
    if validation_status in LIVE_STATUSES:
        score += 10
        reasons.append("candidate passed media validation")
    elif any(fragment in validation_status for fragment in RESTRICTED_FRAGMENTS):
        score -= 20
        reasons.append("candidate validation indicates restricted/auth-required media")
    elif any(fragment in validation_status for fragment in DEAD_FRAGMENTS):
        score -= 20
        reasons.append("candidate validation indicates dead or non-camera media")
    elif validation_status in {"not_validated", "validation_disabled", "rtsp_validation_unavailable"}:
        reasons.append("candidate is not validated; evidence does not imply trust")

    if http_metadata.get("www_authenticate_present"):
        score -= 20
        reasons.append("candidate HTTP metadata advertises authentication")
    if http_metadata.get("http_status") and int(http_metadata.get("http_status") or 0) < 400:
        score += 5
        reasons.append("candidate HTTP metadata shows reachable response")

    score = max(0, min(100, score))
    return score, _dedupe(reasons), signals, matches, protocol


def source_row_evidence_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_url": redact_sensitive_url(row.get("url")),
        "query": row.get("query"),
        "source_type": row.get("source_provider") or row.get("source_kind") or "unknown",
        "source_allowed": not bool(row.get("blocked_reason")),
        "source_blocked": bool(row.get("blocked_reason")),
        "blocked_reason": row.get("blocked_reason"),
        "http_metadata": row.get("http_metadata") or {},
        "camera_evidence_score": row.get("source_camera_evidence_score", 0),
        "camera_evidence_band": row.get("source_camera_evidence_band", "none"),
        "camera_evidence_reasons": row.get("source_camera_evidence_reasons") or [],
        "camera_evidence_signals": row.get("source_camera_evidence_signals") or {},
        "signature_matches": row.get("source_signature_matches") or [],
        "linked_candidate_count": row.get("linked_candidate_count", 0),
        "why_it_mattered": row.get("why_source_mattered") or why_it_mattered(row.get("source_camera_evidence_reasons") or [], prefix="Source"),
    }


def candidate_evidence_record(candidate: Any) -> dict[str, Any]:
    metadata = getattr(candidate, "source_metadata", None) or {}
    return {
        "candidate_url": redact_sensitive_url(getattr(candidate, "stream_url", None)),
        "source_url": redact_sensitive_url(getattr(candidate, "source_url", None)),
        "camera_type": metadata.get("camera_type"),
        "protocol_label": metadata.get("protocol_label"),
        "media_family": metadata.get("media_family"),
        "protocol_confidence": metadata.get("protocol_confidence"),
        "protocol_reasons": metadata.get("protocol_reasons") or [],
        "http_metadata": metadata.get("http_metadata") or {},
        "camera_evidence_score": metadata.get("camera_evidence_score", 0),
        "camera_evidence_band": metadata.get("camera_evidence_band", "none"),
        "camera_evidence_reasons": metadata.get("camera_evidence_reasons") or [],
        "camera_evidence_signals": metadata.get("camera_evidence_signals") or {},
        "signature_matches": metadata.get("signature_matches") or [],
        "scope_status": getattr(candidate, "scope_status", None),
        "validation_status": getattr(candidate, "validation_status", None),
        "trust_level": getattr(candidate, "trust_level", None),
        "candidate_priority_bucket": metadata.get("candidate_priority_bucket"),
        "why_it_mattered": metadata.get("why_candidate_mattered") or why_it_mattered(metadata.get("camera_evidence_reasons") or [], prefix="Candidate"),
    }


def passive_intelligence_summary(candidates: Iterable[Any], source_rows: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    candidate_list = list(candidates)
    source_list = list(source_rows)
    band_counts = Counter(str((getattr(row, "source_metadata", {}) or {}).get("camera_evidence_band") or "none") for row in candidate_list)
    source_band_counts = Counter(str(row.get("source_camera_evidence_band") or row.get("camera_evidence_band") or "none") for row in source_list)
    protocols = Counter(str((getattr(row, "source_metadata", {}) or {}).get("protocol_label") or "unknown") for row in candidate_list)
    signature_counts: Counter[str] = Counter()
    reason_counts: Counter[str] = Counter()
    for candidate in candidate_list:
        metadata = getattr(candidate, "source_metadata", None) or {}
        for match in metadata.get("signature_matches") or []:
            signature_counts[str(match.get("signature_family") or "unknown")] += 1
        for reason in metadata.get("camera_evidence_reasons") or []:
            reason_counts[str(reason)] += 1
    for row in source_list:
        for match in row.get("source_signature_matches") or row.get("signature_matches") or []:
            signature_counts[str(match.get("signature_family") or "unknown")] += 1
        for reason in row.get("source_camera_evidence_reasons") or row.get("camera_evidence_reasons") or []:
            reason_counts[str(reason)] += 1
    return {
        "sources_scored": len(source_list),
        "candidates_scored": len(candidate_list),
        "candidate_evidence_bands": {key: band_counts.get(key, 0) for key in ("very_strong", "strong", "moderate", "weak", "none")},
        "source_evidence_bands": {key: source_band_counts.get(key, 0) for key in ("very_strong", "strong", "moderate", "weak", "none") if source_band_counts.get(key, 0)},
        "very_strong_candidates": band_counts.get("very_strong", 0),
        "strong_candidates": band_counts.get("strong", 0),
        "moderate_candidates": band_counts.get("moderate", 0),
        "weak_candidates": band_counts.get("weak", 0),
        "protocol_label_counts": dict(sorted(protocols.items())),
        "signature_family_counts": dict(sorted(signature_counts.items())),
        "top_evidence_signals": [reason for reason, _count in reason_counts.most_common(10)],
        "top_camera_evidence_reasons": [reason for reason, _count in reason_counts.most_common(10)],
        "validation_prioritized_by_evidence": True,
    }


def add_passive_intelligence_to_dashboard(dashboard: dict[str, Any], candidates: Iterable[Any]) -> dict[str, Any]:
    dashboard["passive_intelligence"] = passive_intelligence_summary(candidates)
    return dashboard


def why_it_mattered(reasons: Iterable[str], *, prefix: str) -> str:
    clean = [str(reason).strip() for reason in reasons if str(reason).strip()]
    if not clean:
        return f"{prefix} had no strong passive camera evidence; it remains review/prioritization-only evidence."
    return f"{prefix} mattered because " + "; ".join(clean[:4]) + "."


def _signature_weight(match: dict[str, Any]) -> int:
    confidence = str(match.get("confidence") or "low").casefold()
    if confidence == "high":
        return 10
    if confidence in {"medium", "moderate"}:
        return 7
    return 4


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _dedupe(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def dataclass_or_dict(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return dict(value)
    return {}
