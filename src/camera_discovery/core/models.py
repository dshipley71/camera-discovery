from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class RuntimeProfile(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    FULL = "full"


class DiscoveryMode(str, Enum):
    BLIND = "blind"
    DIRECTORY = "directory"
    BOTH = "both"
    DIRECT = "direct"


class TrustPolicy(str, Enum):
    TRUSTED_ALLOWED = "trusted_allowed"
    REVIEW_ONLY = "review_only"
    STOP = "stop"


@dataclass
class RunConfig:
    query: str
    output_dir: Path
    profile: RuntimeProfile = RuntimeProfile.FAST
    llm_provider: str = "ollama"
    llm_model: str | None = None

    target_intent_model: str | None = None
    target_intent_timeout: float = 45.0
    target_intent_attempts: int = 1
    target_intent_fallback_model: str | None = None

    geocoder_referee_model: str | None = None
    geocoder_referee_timeout: float = 45.0

    candidate_review_model: str | None = None
    candidate_review_timeout: float = 45.0
    candidate_review_batch_size: int = 8
    max_candidate_reviews: int = 50

    max_search_queries: int = 4
    max_search_results_per_query: int = 5
    max_pages: int = 25
    max_streams: int = 100
    http_timeout: float = 20.0
    user_agent: str = "camera-discovery/0.1 (+public-camera-research)"
    allow_untrusted_review_output: bool = True
    seed_urls: list[str] = field(default_factory=list)
    sources_file: Path | None = None
    discovery_mode: DiscoveryMode = DiscoveryMode.BOTH
    block_patterns: list[str] = field(default_factory=list)
    enable_candidate_geocoding: bool = True
    max_candidate_geocodes: int = 25

    @property
    def validation_enabled(self) -> bool:
        return self.profile in {RuntimeProfile.BALANCED, RuntimeProfile.FULL}

    @property
    def ffprobe_enabled(self) -> bool:
        return self.profile == RuntimeProfile.FULL


@dataclass
class TargetIntent:
    raw_query: str
    canonical_target: str | None = None
    place_name: str | None = None
    scope_type: str | None = None
    admin_region: str | None = None
    country: str | None = None
    camera_type_intent: str | None = None
    alternate_interpretations: list[dict[str, Any]] = field(default_factory=list)
    geocoder_query_variants: list[str] = field(default_factory=list)
    ambiguity: bool = False
    ambiguity_reason: str | None = None
    confidence: float | None = None

    # Optional LLM geometry hints. These are never verified geometry.
    llm_center_lat: float | None = None
    llm_center_lon: float | None = None
    llm_bbox: dict[str, float] | None = None
    llm_geometry_hint_reason: str | None = None


@dataclass
class GeocoderCandidate:
    query: str
    display_name: str
    result_type: str | None = None
    lat: float | None = None
    lon: float | None = None
    bbox: dict[str, float] | None = None
    polygon: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    # Deterministic score/rejection remains the trust boundary.
    score: float = 0.0
    deterministic_score: float = 0.0
    rejected: bool = False
    rejection_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Advisory LLM referee fields. These may influence ranking among candidates
    # that already passed deterministic hard gates, but cannot verify geometry.
    llm_rank: int | None = None
    llm_relevance_score: float | None = None
    llm_referee_recommendation: str | None = None
    llm_referee_reason: str | None = None


@dataclass
class TargetContext:
    user_query: str
    intent: TargetIntent
    target_id: str = "target_1"
    target_index: int = 0
    target_label: str | None = None
    canonical_target: str | None = None
    scope_type: str | None = None
    admin_region: str | None = None
    country: str | None = None
    geocoder_queries: list[str] = field(default_factory=list)
    geocoder_candidates: list[GeocoderCandidate] = field(default_factory=list)
    chosen_candidate: GeocoderCandidate | None = None
    geometry_status: Literal["verified", "unverified_review_only", "missing", "implausible", "ambiguous"] = "missing"
    bbox: dict[str, float] | None = None
    polygon: dict[str, Any] | None = None
    bbox_verified: bool = False
    geometry_source: str | None = None
    trust_policy: TrustPolicy = TrustPolicy.STOP
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CameraCandidate:
    stream_url: str
    source_url: str | None = None
    discovery_method: str = "unknown"
    title: str | None = None
    lat: float | None = None
    lon: float | None = None
    location_text: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    scope_status: Literal["in_scope", "out_of_scope", "unknown", "review"] = "unknown"
    validation_status: str | None = None
    trust_level: Literal["trusted", "untrusted", "rejected"] = "untrusted"
    reasons: list[str] = field(default_factory=list)

    # Multi-target provenance.
    target_id: str | None = None
    target_index: int | None = None
    target_label: str | None = None

    # Advisory LLM semantic-review fields. These do not validate streams.
    llm_semantic_decision: Literal["in_scope", "out_of_scope", "review", "unknown"] | None = None
    llm_semantic_confidence: float | None = None
    llm_semantic_reason: str | None = None

    # Coordinate provenance. Coordinates are either extracted from source data
    # or produced by an explicit geocoder call against candidate metadata.
    coordinate_source: str | None = None
    geocoded_query: str | None = None
    geocoded_display_name: str | None = None

    @property
    def has_coordinates(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass
class CandidateSet:
    raw: list[CameraCandidate] = field(default_factory=list)
    unique: list[CameraCandidate] = field(default_factory=list)
    coordinate_bearing: list[CameraCandidate] = field(default_factory=list)
    in_scope: list[CameraCandidate] = field(default_factory=list)
    review: list[CameraCandidate] = field(default_factory=list)
    rejected: list[CameraCandidate] = field(default_factory=list)

    @classmethod
    def merge(cls, sets: list[CandidateSet]) -> CandidateSet:
        raw = [c for s in sets for c in s.raw]
        unique_by_key: dict[tuple[str, str | None], CameraCandidate] = {}
        for s in sets:
            for c in s.unique:
                unique_by_key.setdefault((c.stream_url.split("#", 1)[0], c.target_id), c)
        unique = list(unique_by_key.values())
        return cls(
            raw=raw,
            unique=unique,
            coordinate_bearing=[c for c in unique if c.has_coordinates],
            in_scope=[c for c in unique if c.scope_status == "in_scope"],
            review=[c for c in unique if c.scope_status in {"review", "unknown", "in_scope"}],
            rejected=[c for c in unique if c.scope_status == "out_of_scope"],
        )


@dataclass
class ValidationSummary:
    validation_enabled: bool = False
    ffprobe_enabled: bool = False
    attempted: int = 0
    live: int = 0
    dead: int = 0
    unknown: int = 0
    skipped: int = 0


@dataclass
class OutputSummary:
    trusted_geojson_created: bool = False
    trusted_geojson_features_written: int = 0
    untrusted_geojson_created: bool = False
    untrusted_geojson_features_written: int = 0
    review_artifacts_zip: str | None = None
    map_html: str | None = None
    camera_candidates_table_csv: str | None = None
    camera_candidates_table_rows: int = 0


@dataclass
class RunState:
    config: RunConfig
    targets: list[TargetContext] = field(default_factory=list)
    target: TargetContext | None = None  # Convenience alias for the first target when present.
    candidates: CandidateSet = field(default_factory=CandidateSet)
    candidate_sets_by_target: dict[str, CandidateSet] = field(default_factory=dict)
    validation: ValidationSummary = field(default_factory=ValidationSummary)
    outputs: OutputSummary = field(default_factory=OutputSummary)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def conv(obj):
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, Enum):
                return obj.value
            if hasattr(obj, "__dataclass_fields__"):
                return {k: conv(v) for k, v in asdict(obj).items()}
            if isinstance(obj, list):
                return [conv(v) for v in obj]
            if isinstance(obj, dict):
                return {k: conv(v) for k, v in obj.items()}
            return obj

        return conv(self)
