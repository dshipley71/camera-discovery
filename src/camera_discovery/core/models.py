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


class HarvestInputMode(str, Enum):
    HANDOFF_ONLY = "handoff-only"
    SEED = "seed"


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

    # LLM-assisted fallback coordinate enrichment. The LLM may infer place-name
    # query variants from candidate evidence, but never coordinates. Nominatim
    # remains the only source of geocoded lat/lon for this fallback.
    location_inference_model: str | None = None
    location_inference_timeout: float = 45.0
    enable_llm_location_inference: bool = True
    max_llm_location_inferences: int = 150
    llm_location_inference_min_confidence: float = 0.70

    candidate_review_model: str | None = None
    candidate_review_timeout: float = 45.0
    candidate_review_batch_size: int = 8
    max_candidate_reviews: int = 150

    max_search_queries: int = 4
    max_search_results_per_query: int = 5
    max_pages: int = 25
    max_hls_candidates: int = 100
    max_image_snapshot_candidates: int = 50
    max_total_candidates: int = 150
    # Deprecated: superseded by max_hls_candidates, max_image_snapshot_candidates,
    # and max_total_candidates. Kept for compatibility with older callers.
    max_streams: int = 150
    max_directory_pages: int = 8
    max_structured_endpoints_per_page: int = 20

    # Browser/network capture is an optional second-stage extraction path. Static
    # extraction runs first; these limits prevent dynamic rendering from consuming
    # an entire discovery run.
    enable_browser_capture: bool = True
    browser_backend: str = "playwright"
    browser_capture_timeout_ms: int = 15000
    browser_capture_min_score: int = 3
    max_browser_capture_pages: int = 20
    max_browser_capture_pages_blind: int = 6
    max_browser_capture_pages_directory: int = 12
    max_browser_capture_pages_per_host: int = 3
    browser_capture_settle_ms: int = 1000
    browser_capture_scroll: bool = False
    max_browser_json_endpoints_per_page: int = 10
    max_browser_network_events_logged_per_page: int = 50

    asset_host_promotion_threshold: int = 3
    max_state_scale_candidate_geocodes: int = 150
    http_timeout: float = 20.0
    validation_workers: int = 24
    user_agent: str = "camera-discovery/0.1 (+public-camera-research)"
    allow_untrusted_review_output: bool = True
    seed_urls: list[str] = field(default_factory=list)
    sources_file: Path | None = None
    discovery_mode: DiscoveryMode = DiscoveryMode.BOTH
    block_patterns: list[str] = field(default_factory=list)
    enable_candidate_geocoding: bool = True
    max_candidate_geocodes: int = 150

    # Real image snapshot validation fetches image URLs twice with cache-busting
    # headers/parameters and compares response freshness. It only runs when
    # validation is enabled by the selected runtime profile.
    image_snapshot_refresh_delay_seconds: float = 2.0

    # Optional harvest handoff/inventory file used by the normal run workflow.
    # handoff-only processes only the loaded handoff candidates; seed also runs
    # native discovery and merges the two candidate sets. Neither mode bypasses
    # target resolution, scope, validation, trust policy, or outputs.
    harvest_input: Path | None = None
    harvest_input_mode: HarvestInputMode = HarvestInputMode.HANDOFF_ONLY

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

    # Preferred target geometry hierarchy. Primary geometry is the actual
    # Nominatim/OSM boundary polygon or multipolygon when available. Fallback
    # geometry is the rectangular Nominatim boundingbox. Last fallback geometry
    # is only a generic padded search box when no usable Nominatim shape/bbox
    # exists. ``bbox`` remains the effective search/scope bbox for backward
    # compatibility with older callers.
    target_geometry_geojson: dict[str, Any] | None = None
    primary_geometry_geojson: dict[str, Any] | None = None
    primary_geometry_source: str | None = None
    fallback_geometry_bbox: dict[str, float] | None = None
    fallback_geometry_source: str | None = None
    last_fallback_geometry_bbox: dict[str, float] | None = None
    last_fallback_geometry_source: str | None = None

    # Target geometry provenance. ``bbox`` is the effective bbox consumed by
    # downstream scope checks and maps. ``nominatim_bbox`` preserves the accepted
    # raw geocoder bbox when a small precise target must be padded to a practical
    # search extent. LLM geometry hints and no-geocoder fallbacks must not set
    # these as verified geocoder geometry.
    nominatim_bbox: dict[str, float] | None = None
    effective_bbox: dict[str, float] | None = None
    bbox_padding_applied: bool = False
    bbox_padding_reason: str | None = None
    bbox_min_side_miles: float | None = None

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

    # Coordinate provenance. Coordinates are either extracted from source data,
    # geocoded from candidate metadata, or geocoded from LLM-inferred place names
    # derived from candidate evidence. The LLM fallback never supplies coordinates.
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
        """Merge per-target candidate sets with deterministic first-seen semantics.

        The unique-candidate dedupe key is ``(stream_url_without_fragment,
        target_id)``. URL fragments are ignored because they do not identify a
        different stream endpoint for this pipeline, while ``target_id`` is kept
        in the key so the same stream discovered for different targets remains
        represented once per target.

        When multiple candidates collide on the same key, the first candidate
        encountered in the supplied ``sets`` order is retained and later
        duplicates are dropped without merging enrichment, coordinate,
        validation, source-metadata, or target-provenance fields. This preserves
        deterministic insertion order and avoids accidental priority decisions
        hidden inside merge order. Any future enrichment-priority or
        source-quality behavior must be implemented as an explicit merge
        strategy rather than changing this implicit first-seen contract.
        """
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
class HarvestConfig:
    query: str
    output_dir: Path
    discovery_mode: DiscoveryMode = DiscoveryMode.BOTH
    seed_urls: list[str] = field(default_factory=list)
    seed_file: Path | None = None
    sources_file: Path | None = None
    block_patterns: list[str] = field(default_factory=list)
    max_urls: int = 10000  # 0 means unlimited final output
    media: list[str] = field(default_factory=list)
    max_search_queries: int = 40
    max_search_results_per_query: int = 50
    max_source_rows: int = 5000
    max_pages_per_source: int = 25
    max_structured_endpoints_per_page: int = 500
    enable_browser_capture: bool = True
    browser_backend: str = "playwright"
    browser_capture_timeout_ms: int = 15000
    browser_capture_settle_ms: int = 1000
    browser_capture_scroll: bool = False
    max_browser_pages: int = 1000
    max_browser_pages_per_host: int = 100
    max_browser_json_endpoints_per_page: int = 100
    max_browser_network_events_logged_per_page: int = 100
    include_source_metadata: bool = True
    write_intermediate_records: bool = False
    image_asset_filter: str = "raw"
    http_timeout: float = 20.0
    user_agent: str = "camera-discovery/0.1 (+public-camera-research)"


@dataclass
class HarvestedMediaAsset:
    asset_id: str
    camera_record_id: str | None
    url: str
    media_type: str
    asset_role: str | None = None
    asset_field: str | None = None
    source_url: str | None = None
    source_endpoint_url: str | None = None
    source_page_url: str | None = None
    source_provider: str | None = None
    source_name: str | None = None
    discovery_method: str = "unknown"
    json_record_path: str | None = None
    field_path: str | None = None
    date: str | None = None
    time: str | None = None
    timestamp: str | None = None
    last_updated: str | None = None
    last_refresh: str | None = None
    image_description: str | None = None
    current_image_update_frequency: str | int | float | None = None
    reference_image_update_frequency: str | int | float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarvestedCameraRecord:
    camera_record_id: str
    camera_id: str | None = None
    source_endpoint_url: str | None = None
    source_page_url: str | None = None
    source_provider: str | None = None
    source_name: str | None = None
    json_record_path: str | None = None

    title: str | None = None
    description: str | None = None
    location_text: str | None = None

    lat: float | None = None
    lon: float | None = None
    coordinate_source: str | None = None
    coordinates: Any | None = None

    direction: str | None = None
    bearing: float | None = None
    heading: float | None = None
    orientation: str | None = None

    in_service: bool | None = None
    status: str | None = None
    status_source: str | None = None

    date: str | None = None
    time: str | None = None
    timestamp: str | None = None
    last_updated: str | None = None
    last_refresh: str | None = None

    image_description: str | None = None
    current_image_update_frequency: str | int | float | None = None
    reference_image_update_frequency: str | int | float | None = None

    media_assets: list[HarvestedMediaAsset] = field(default_factory=list)
    normalized_fields: dict[str, Any] = field(default_factory=dict)
    field_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_record: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveredEndpointRecord:
    endpoint_url: str
    endpoint_type: str
    source_page_url: str | None = None
    source_provider: str | None = None
    source_name: str | None = None
    first_seen_method: str = "unknown"
    record_count: int = 0
    camera_record_count: int = 0
    media_asset_count: int = 0
    has_coordinates: bool = False
    has_timestamps: bool = False
    has_service_status: bool = False
    has_refresh_metadata: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarvestedUrlRecord:
    url: str
    media_type: str
    source_url: str | None = None
    discovery_method: str = "unknown"
    title: str | None = None
    description: str | None = None
    location_text: str | None = None
    camera_id: str | None = None
    source_name: str | None = None
    source_provider: str | None = None

    # Structured-harvest grouping/provenance. These fields link flat URL rows
    # back to their source camera object and source JSON field when available.
    camera_record_id: str | None = None
    asset_id: str | None = None
    asset_role: str | None = None
    asset_field: str | None = None
    field_path: str | None = None
    source_endpoint_url: str | None = None
    source_page_url: str | None = None
    json_record_path: str | None = None

    # Deterministically promoted source metadata. Harvest mode does not infer,
    # geocode, validate, or normalize these from outside services; these fields
    # are populated only when coordinates/orientation/time/status values are
    # present in collected camera/source metadata. The full original metadata
    # remains in ``metadata`` below.
    lat: float | None = None
    lon: float | None = None
    coordinate_source: str | None = None
    direction: str | None = None
    bearing: float | None = None
    heading: float | None = None
    orientation: str | None = None
    in_service: bool | None = None
    status: str | None = None
    date: str | None = None
    time: str | None = None
    timestamp: str | None = None
    last_updated: str | None = None
    last_refresh: str | None = None
    image_description: str | None = None
    current_image_update_frequency: str | int | float | None = None
    reference_image_update_frequency: str | int | float | None = None

    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HarvestResult:
    raw_count: int = 0
    unique_count: int = 0
    written_count: int = 0
    records: list[HarvestedUrlRecord] = field(default_factory=list)
    camera_records: list[HarvestedCameraRecord] = field(default_factory=list)
    media_assets: list[HarvestedMediaAsset] = field(default_factory=list)
    discovered_endpoints: list[DiscoveredEndpointRecord] = field(default_factory=list)
    by_media_type: dict[str, int] = field(default_factory=dict)
    by_source_provider: dict[str, int] = field(default_factory=dict)
    by_source_host: dict[str, int] = field(default_factory=dict)
    output_files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationSummary:
    """Validation counters.

    HLS validation may emit active_live_verified when FULL-profile segment
    probing succeeds, or active_playlist_dead_segments when the playlist is
    reachable but its first media/variant segment cannot be reached.
    """

    validation_enabled: bool = False
    ffprobe_enabled: bool = False
    validation_workers: int = 0
    http_timeout: float = 0.0
    parallel_validation: bool = False
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
    coordinate_bearing_candidates: int = 0
    coordinate_bearing_geojson_features_written: int = 0
    coordinate_bearing_without_geojson: int = 0
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
