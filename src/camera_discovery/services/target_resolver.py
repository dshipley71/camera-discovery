from __future__ import annotations

import math
import os
import re
import time
from dataclasses import asdict
from typing import Any
from urllib.parse import urlencode

import httpx

from camera_discovery.core.models import (
    GeocoderCandidate,
    RunConfig,
    RuntimeProfile,
    TargetContext,
    TargetIntent,
    TrustPolicy,
)
from camera_discovery.llm.base import ChatMessage, LLMClient
from camera_discovery.llm.factory import build_geocoder_referee_client, build_llm_client, build_target_intent_client
from camera_discovery.utils.io import write_json
from camera_discovery.utils.json_utils import extract_json_object

SCOPE_WORDS = ("metropolitan area", "metro area", "metropolitan", "greater area", "greater", "county", "state")
PLACE_LIKE_SCOPES = {"place", "city", "county", "metro", "region", "state", "country"}
LOCATION_CLAUSE_RE = re.compile(r"\b(?:in|from|near|around)\s+(.+)$", re.I)
US_STATE_NAMES = {
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
    "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi",
    "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire", "New Jersey", "New Mexico",
    "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon", "Pennsylvania",
    "Rhode Island", "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming", "District of Columbia",
}

CAMERA_TYPE_WORDS = {
    "camera", "cameras", "cam", "cams", "webcam", "webcams", "traffic", "weather",
    "public", "live", "hls", "stream", "streams", "streaming", "video", "videos",
    "road", "roads", "highway", "highways", "freeway", "freeways", "transportation",
}
CAMERA_TYPE_PATTERNS = {
    "traffic": ("traffic", "road", "roads", "highway", "highways", "freeway", "freeways", "transportation"),
    "weather": ("weather",),
    "webcam": ("webcam", "webcams"),
}


class TargetResolver:
    """Resolve one or more target geographies with LLM interpretation plus deterministic verification.

    The LLM extracts one or more target intents and ranks geocoder candidates as an
    advisory evidence interpreter. Geometry trust remains deterministic: only bbox,
    result-type, scope, and admin/country checks can verify a target.
    """

    def __init__(
        self,
        config: RunConfig,
        llm_client: LLMClient | None = None,
        geocoder_referee_client: LLMClient | None = None,
    ):
        self.config = config
        self.llm_client = llm_client
        self.geocoder_referee_client = geocoder_referee_client
        self.logs_dir = config.output_dir / "logs"

    def resolve(self) -> TargetContext:
        """Backward-compatible single-target API. Returns the first resolved target."""
        targets = self.resolve_all()
        if not targets:
            intent = TargetIntent(raw_query=self.config.query, canonical_target=self.config.query, scope_type="unknown")
            return TargetContext(
                user_query=self.config.query,
                intent=intent,
                target_id="target_1",
                target_index=0,
                target_label=self.config.query,
                canonical_target=self.config.query,
                scope_type="unknown",
                trust_policy=TrustPolicy.STOP,
                stop_reason="No target intent was extracted from the user query.",
            )
        return targets[0]

    def resolve_all(self) -> list[TargetContext]:
        """Resolve every place/location requested in the user query."""
        intents = self._build_target_intents()
        targets = [self._resolve_intent(intent, i) for i, intent in enumerate(intents)]
        write_json(self.logs_dir / "target_resolution_all.json", {"targets": [self._target_summary(t) for t in targets]})
        return targets

    def _resolve_intent(self, intent: TargetIntent, index: int) -> TargetContext:
        label = intent.canonical_target or intent.place_name or f"target {index + 1}"
        target_id = _slug(label, default=f"target_{index + 1}")
        target_logs = self.logs_dir / "targets" / target_id
        queries = self._build_geocoder_queries(intent)
        candidates = self._geocode_all(queries)
        ranked = self._score_candidates(candidates, intent, target_logs)
        chosen = next((c for c in ranked if not c.rejected), None)

        ctx = TargetContext(
            user_query=self.config.query,
            intent=intent,
            target_id=target_id,
            target_index=index,
            target_label=label,
            canonical_target=label,
            scope_type=intent.scope_type or "place",
            admin_region=intent.admin_region,
            country=intent.country,
            geocoder_queries=queries,
            geocoder_candidates=ranked,
            chosen_candidate=chosen,
        )
        if chosen and chosen.bbox:
            ctx.bbox = chosen.bbox
            ctx.polygon = chosen.polygon
            ctx.bbox_verified = True
            ctx.geometry_source = "geocoder"
            ctx.geometry_status = "verified"
            ctx.trust_policy = TrustPolicy.REVIEW_ONLY if not self.config.validation_enabled else TrustPolicy.TRUSTED_ALLOWED
            if not self.config.validation_enabled:
                ctx.warnings.append("Validation disabled; trusted output blocked.")
        elif intent.llm_bbox:
            ctx.bbox = intent.llm_bbox
            ctx.bbox_verified = False
            ctx.geometry_source = "llm_hint"
            ctx.geometry_status = "unverified_review_only"
            if self.config.profile == RuntimeProfile.FAST and self.config.allow_untrusted_review_output:
                ctx.trust_policy = TrustPolicy.REVIEW_ONLY
                ctx.warnings.append("Only unverified LLM geometry hint available; review-only.")
            else:
                ctx.trust_policy = TrustPolicy.STOP
                ctx.stop_reason = "Only unverified LLM geometry hint available."
        else:
            ctx.geometry_status = "missing"
            if self.config.profile == RuntimeProfile.FAST and self.config.allow_untrusted_review_output:
                ctx.trust_policy = TrustPolicy.REVIEW_ONLY
                ctx.warnings.append("No verified target geometry; Fast mode proceeds review-only.")
            else:
                ctx.trust_policy = TrustPolicy.STOP
                ctx.stop_reason = "No verified target bbox or polygon was resolved."
        self._write_diagnostics(intent, queries, ranked, ctx, target_logs)
        return ctx

    def _build_target_intents(self) -> list[TargetIntent]:
        deterministic = self._deterministic_intents()
        raw = self._call_target_intent_llm()
        if raw is None:
            # The application still requires a real LLM provider. This branch
            # handles an unavailable/timed-out advisory extraction call by using
            # the deterministic query parser to preserve the user request and
            # keep Fast review-only runs from crashing before discovery.
            write_json(
                self.logs_dir / "target_intent.json",
                {
                    "targets": [asdict(i) for i in deterministic],
                    "source": "deterministic_after_llm_failure",
                    "warning": "Target-intent LLM call failed or timed out; deterministic parser used for target clauses.",
                },
            )
            return deterministic
        data = extract_json_object(raw)
        targets_data = data.get("targets") if isinstance(data.get("targets"), list) else None
        if targets_data:
            intents: list[TargetIntent] = []
            for i, item in enumerate(targets_data):
                if not isinstance(item, dict):
                    continue
                fallback = deterministic[i] if i < len(deterministic) else self._fallback_intent_from_text(str(item.get("canonical_target") or item.get("place_name") or self.config.query))
                intents.append(self._intent_from_dict(item, fallback))
            if intents:
                write_json(self.logs_dir / "target_intent.json", {"targets": [asdict(i) for i in intents], "source": "llm"})
                return intents
        # Backward-compatible single-object target intent, but do not collapse
        # deterministically extracted multi-target clauses if the LLM omitted a list.
        if len(deterministic) > 1 and not targets_data:
            write_json(self.logs_dir / "target_intent.json", {"targets": [asdict(i) for i in deterministic], "source": "deterministic_multi_target_guard"})
            return deterministic
        intent = self._intent_from_dict(data, deterministic[0] if deterministic else self._fallback_intent_from_text(self.config.query))
        write_json(self.logs_dir / "target_intent.json", {"targets": [asdict(intent)], "source": "llm_single_object"})
        return [intent]

    def _call_target_intent_llm(self) -> str | None:
        if not getattr(self.config, "enable_target_intent_llm", True):
            write_json(
                self.logs_dir / "target_intent_llm_error.json",
                {"status": "skipped", "reason": "target_intent_llm_disabled_by_preflight"},
            )
            return None
        prompt = self._target_intent_prompt(self.config.query)
        system = ChatMessage("system", "Return compact strict JSON only. No prose.")
        user = ChatMessage("user", prompt)
        attempts = max(1, getattr(self.config, "target_intent_attempts", 1))
        errors: list[dict[str, Any]] = []

        client_specs: list[tuple[str, LLMClient]] = []
        if self.llm_client is not None:
            client_specs.append((getattr(self.llm_client, "model", "injected_client"), self.llm_client))
        else:
            primary = build_target_intent_client(self.config)
            client_specs.append((getattr(primary, "model", "primary"), primary))
            fallback_model = getattr(self.config, "target_intent_fallback_model", None)
            primary_model = getattr(primary, "model", None)
            if fallback_model and fallback_model != primary_model:
                provider = (os.getenv("CAMERA_DISCOVERY_TARGET_INTENT_PROVIDER") or self.config.llm_provider).strip().lower()
                client_specs.append((fallback_model, build_llm_client(provider, fallback_model, timeout=self.config.target_intent_timeout)))

        for model, client in client_specs:
            for attempt in range(1, attempts + 1):
                try:
                    raw = client.chat([system, user], temperature=0.0)
                    write_json(
                        self.logs_dir / "target_intent_llm_raw.json",
                        {"raw": raw, "model": model, "attempt": attempt, "errors_before_success": errors},
                    )
                    return raw
                except Exception as exc:
                    errors.append({"model": model, "attempt": attempt, "error_type": type(exc).__name__, "error": str(exc)})
        write_json(self.logs_dir / "target_intent_llm_error.json", {"errors": errors})
        return None

    def _deterministic_intents(self) -> list[TargetIntent]:
        phrases = self._extract_target_phrases(self.config.query)
        return [self._fallback_intent_from_text(p) for p in phrases] or [self._fallback_intent_from_text(self.config.query)]

    def _fallback_intent_from_text(self, target: str) -> TargetIntent:
        target = self._clean_target_phrase(target)
        scope = self._infer_scope(target)
        admin = self._infer_admin_hint(target)
        country = "United States" if admin and admin in US_STATE_NAMES else None
        return TargetIntent(
            raw_query=self.config.query.strip(),
            canonical_target=target,
            place_name=self._strip_scope_words(target),
            scope_type=scope,
            admin_region=admin,
            country=country,
            camera_type_intent=self._infer_camera_type_intent(self.config.query),
            geocoder_query_variants=[target],
            confidence=0.5,
        )

    def _intent_from_dict(self, data: dict[str, Any], fallback: TargetIntent) -> TargetIntent:
        variants = data.get("geocoder_query_variants") if isinstance(data.get("geocoder_query_variants"), list) else []
        admin = data.get("admin_region") or fallback.admin_region
        country = data.get("country") or fallback.country
        canonical = data.get("canonical_target") or data.get("target") or fallback.canonical_target
        place_name = data.get("place_name") or fallback.place_name
        camera_type_intent = data.get("camera_type_intent") or fallback.camera_type_intent

        # LLMs can confuse a camera category with a location, e.g. returning
        # "traffic_cameras" as the target for "traffic cameras from California".
        # Treat camera-only phrases as camera intent and preserve the deterministic
        # geographic fallback from the original user query.
        if canonical and _looks_like_camera_type_only(str(canonical)):
            camera_type_intent = self._infer_camera_type_intent(str(canonical)) or camera_type_intent
            canonical = fallback.canonical_target
            place_name = fallback.place_name
        if place_name and _looks_like_camera_type_only(str(place_name)):
            place_name = fallback.place_name

        if admin and canonical and admin.casefold() not in canonical.casefold():
            variants.append(f"{canonical}, {admin}")
        if fallback.canonical_target and canonical and fallback.canonical_target.casefold() != str(canonical).casefold():
            variants.append(fallback.canonical_target)
        return TargetIntent(
            raw_query=fallback.raw_query,
            canonical_target=canonical,
            place_name=place_name,
            scope_type=data.get("scope_type") or fallback.scope_type,
            admin_region=admin,
            country=country,
            camera_type_intent=camera_type_intent,
            alternate_interpretations=data.get("alternate_interpretations") if isinstance(data.get("alternate_interpretations"), list) else [],
            geocoder_query_variants=[str(v) for v in variants if not _looks_like_camera_type_only(str(v))] + fallback.geocoder_query_variants,
            ambiguity=bool(data.get("ambiguity", fallback.ambiguity)),
            ambiguity_reason=data.get("ambiguity_reason") or fallback.ambiguity_reason,
            confidence=_float_or_none(data.get("confidence")) or fallback.confidence,
            llm_center_lat=_float_or_none(data.get("llm_center_lat")),
            llm_center_lon=_float_or_none(data.get("llm_center_lon")),
            llm_bbox=data.get("llm_bbox") if isinstance(data.get("llm_bbox"), dict) else None,
            llm_geometry_hint_reason=data.get("llm_geometry_hint_reason"),
        )

    def _build_geocoder_queries(self, intent: TargetIntent) -> list[str]:
        alt_targets = [a.get("target") for a in intent.alternate_interpretations if isinstance(a, dict) and a.get("target")]
        parts = [v for v in [intent.canonical_target, intent.place_name, *intent.geocoder_query_variants, *alt_targets] if v]
        expanded: list[str] = []
        for item in parts:
            expanded.append(str(item))
            stripped = self._strip_scope_words(str(item))
            if stripped and stripped != item:
                expanded.append(stripped)
            if intent.admin_region and intent.admin_region.casefold() not in str(item).casefold():
                expanded.append(f"{stripped or item}, {intent.admin_region}")
            if intent.country and intent.country.casefold() not in str(item).casefold():
                expanded.append(f"{item}, {intent.country}")
        return _dedupe([q.strip(" ,") for q in expanded if q and q.strip(" ,")])[:12]

    def _geocode_all(self, queries: list[str]) -> list[GeocoderCandidate]:
        out: list[GeocoderCandidate] = []
        for q in queries:
            try:
                out.extend(self._geocode(q))
            except Exception as exc:
                out.append(GeocoderCandidate(query=q, display_name="", rejected=True, rejection_reasons=[f"geocoder_error:{exc!r}"]))
        return out

    def _geocode(self, query: str) -> list[GeocoderCandidate]:
        url = f"https://nominatim.openstreetmap.org/search?{urlencode({'q': query, 'format': 'jsonv2', 'limit': '5', 'polygon_geojson': '1', 'addressdetails': '1'})}"
        with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
            time.sleep(1.0)
            rows = client.get(url)
            rows.raise_for_status()
            data = rows.json()
        return [
            GeocoderCandidate(
                query=query,
                display_name=str(r.get("display_name") or ""),
                result_type=str(r.get("type") or r.get("class") or ""),
                lat=_float_or_none(r.get("lat")),
                lon=_float_or_none(r.get("lon")),
                bbox=_bbox_from_nominatim(r.get("boundingbox")),
                polygon=r.get("geojson") if isinstance(r.get("geojson"), dict) else None,
                raw=r,
            )
            for r in data
        ]

    def _score_candidates(self, candidates: list[GeocoderCandidate], intent: TargetIntent, target_logs) -> list[GeocoderCandidate]:
        for c in candidates:
            self._score_candidate(c, intent)
            c.deterministic_score = c.score
        self._apply_llm_geocoder_referee(candidates, intent, target_logs)
        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _score_candidate(self, c: GeocoderCandidate, intent: TargetIntent) -> None:
        if not c.display_name:
            c.rejected = True
            c.rejection_reasons.append("empty_geocoder_result")
            return
        score = 0.0
        display = c.display_name.casefold()
        scope = (intent.scope_type or "place").casefold()
        if c.bbox:
            valid, reason = _bbox_plausible(c.bbox, scope)
            if not valid:
                c.rejected = True
                c.rejection_reasons.append(reason)
            else:
                score += 40
        else:
            c.rejected = True
            c.rejection_reasons.append("missing_bbox")
        if scope in PLACE_LIKE_SCOPES and (c.result_type or "").casefold() in {"house", "road", "address", "building", "postcode", "marketplace", "shop"}:
            c.rejected = True
            c.rejection_reasons.append("result_type_too_specific_for_scope")
        if intent.admin_region and intent.admin_region.casefold() in display:
            score += 20
        elif intent.admin_region and intent.admin_region.casefold() not in display:
            c.rejected = True
            c.rejection_reasons.append("admin_hint_not_in_display_name")
        if intent.country and intent.country.casefold() in display:
            score += 10
        if intent.place_name and any(tok in display for tok in _tokens(intent.place_name)):
            score += 10
        if c.polygon:
            score += 5
        c.score = score

    def _apply_llm_geocoder_referee(self, candidates: list[GeocoderCandidate], intent: TargetIntent, target_logs) -> None:
        """Ask an LLM to rank candidates semantically without overriding hard gates."""
        if not candidates:
            return
        if not getattr(self.config, "enable_geocoder_referee_llm", True):
            write_json(target_logs / "geocoder_referee.json", {"status": "skipped", "reason": "geocoder_referee_llm_disabled_by_preflight"})
            return
        try:
            client = self.geocoder_referee_client or build_geocoder_referee_client(self.config)
        except Exception as exc:
            write_json(target_logs / "geocoder_referee.json", {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:1000]})
            return
        payload = [
            {
                "index": i,
                "query": c.query,
                "display_name": c.display_name,
                "result_type": c.result_type,
                "bbox": c.bbox,
                "deterministic_rejected": c.rejected,
                "deterministic_score": c.deterministic_score,
                "rejection_reasons": c.rejection_reasons,
            }
            for i, c in enumerate(candidates[:12])
        ]
        try:
            raw = client.chat(
                [
                    ChatMessage("system", "Return strict JSON only. You are an advisory geocoder-candidate referee; you cannot verify geometry."),
                    ChatMessage("user", self._geocoder_referee_prompt(intent, payload)),
                ],
                temperature=0.0,
            )
            data = extract_json_object(raw)
        except Exception as exc:
            write_json(target_logs / "geocoder_referee.json", {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)[:1000], "model": getattr(client, "model", None)})
            return
        write_json(target_logs / "geocoder_referee_llm_raw.json", {"raw": raw, "model": getattr(client, "model", None)})
        write_json(target_logs / "geocoder_referee.json", data)
        rankings = data.get("rankings") if isinstance(data.get("rankings"), list) else []
        by_index = {i: c for i, c in enumerate(candidates)}
        for row in rankings:
            if not isinstance(row, dict):
                continue
            idx = _int_or_none(row.get("index"))
            if idx is None or idx not in by_index:
                continue
            c = by_index[idx]
            c.llm_rank = _int_or_none(row.get("rank"))
            c.llm_relevance_score = _float_or_none(row.get("confidence"))
            c.llm_referee_recommendation = str(row.get("recommendation") or "review")[:32]
            c.llm_referee_reason = str(row.get("reason") or "")[:500]
            if c.rejected:
                c.warnings.append("LLM referee reviewed deterministic-rejected candidate; hard rejection preserved.")
                continue
            conf = max(0.0, min(1.0, c.llm_relevance_score or 0.0))
            rec = (c.llm_referee_recommendation or "review").casefold()
            if rec in {"accept", "best", "in_scope"}:
                c.score += 15.0 * conf
            elif rec in {"reject", "out_of_scope"}:
                c.score -= 10.0 * conf
            else:
                c.score += 3.0 * conf

    def _write_diagnostics(self, intent: TargetIntent, queries: list[str], candidates: list[GeocoderCandidate], ctx: TargetContext, target_logs) -> None:
        write_json(target_logs / "target_intent.json", asdict(intent))
        write_json(target_logs / "geocoder_query_variants.json", {"queries": queries})
        write_json(target_logs / "geocoder_candidate_scores.json", {"candidates": [asdict(c) for c in candidates]})
        write_json(target_logs / "target_resolution.json", self._target_summary(ctx))
        # Convenience top-level files remain for single-target users.
        if ctx.target_index == 0:
            write_json(self.logs_dir / "target_intent.json", asdict(intent))
            write_json(self.logs_dir / "geocoder_query_variants.json", {"queries": queries})
            write_json(self.logs_dir / "geocoder_candidate_scores.json", {"candidates": [asdict(c) for c in candidates]})
            write_json(self.logs_dir / "target_resolution.json", self._target_summary(ctx))

    def _target_summary(self, ctx: TargetContext) -> dict[str, Any]:
        return {
            "target_id": ctx.target_id,
            "target_index": ctx.target_index,
            "target_label": ctx.target_label,
            "canonical_target": ctx.canonical_target,
            "scope_type": ctx.scope_type,
            "bbox": ctx.bbox,
            "bbox_verified": ctx.bbox_verified,
            "geometry_status": ctx.geometry_status,
            "geometry_source": ctx.geometry_source,
            "trust_policy": ctx.trust_policy.value,
            "warnings": ctx.warnings,
            "stop_reason": ctx.stop_reason,
            "llm_geometry_hint_trusted": False,
            "chosen_candidate": asdict(ctx.chosen_candidate) if ctx.chosen_candidate else None,
        }

    def _target_intent_prompt(self, query: str) -> str:
        return (
            "Extract camera-search target intent. Return JSON only: "
            "{\"targets\":[{\"canonical_target\":str,\"place_name\":str,\"scope_type\":str,"
            "\"admin_region\":str|null,\"country\":str|null,\"camera_type_intent\":str,"
            "\"geocoder_query_variants\":[str],\"ambiguity\":bool,\"confidence\":number}]} . "
            "Rules: camera terms such as traffic/weather/webcam/live/HLS are camera_type_intent, not places. "
            "Example: 'traffic cameras from California' => target California, camera_type_intent traffic. "
            "Do not verify geometry or trusted output. "
            f"Query: {query!r}"
        )

    def _geocoder_referee_prompt(self, intent: TargetIntent, candidates: list[dict[str, Any]]) -> str:
        return (
            "Given the target intent and geocoder candidates, rank the candidates by semantic match to the user's intended place. "
            "Do not verify geometry, do not override deterministic rejection reasons, and do not decide trusted output. "
            "Return JSON: {\"rankings\":[{\"index\":0,\"rank\":1,\"recommendation\":\"accept|review|reject\","
            "\"confidence\":0.0,\"reason\":\"short reason\"}]}\n"
            f"Target intent: {asdict(intent)}\nCandidates: {candidates}"
        )

    def _extract_target_phrases(self, query: str) -> list[str]:
        match = LOCATION_CLAUSE_RE.search(query)
        clause = match.group(1) if match else query
        clause = re.sub(r"\b(?:public|live|camera|cameras|cam|cams|webcam|webcams|traffic|weather|hls|streams?|from|in)\b", " ", clause, flags=re.I)
        clause = re.sub(r"\s+", " ", clause).strip(" .,;|")
        # Split explicit multi-location conjunctions without splitting place/admin commas.
        parts = re.split(r"\s+(?:and|&)\s+|\s*;\s*|\s*\|\s*", clause, flags=re.I)
        return [re.sub(r"^(?:the state of|state of|the city of|city of)\s+", "", p.strip(" .,"), flags=re.I) for p in parts if p and p.strip(" .,;|")]


    def _clean_target_phrase(self, target: str) -> str:
        target = target.strip(" .")
        target = re.sub(r"^(?:the state of|state of|the city of|city of)\s+", "", target, flags=re.I)
        target = re.sub(r"\b(?:public|live|camera|cameras|cam|cams|webcam|webcams|traffic|weather|hls|streams?)\b", " ", target, flags=re.I)
        return re.sub(r"\s+", " ", target).strip(" ,")

    def _infer_camera_type_intent(self, text: str) -> str:
        lowered = text.replace("_", " ").casefold()
        for intent, terms in CAMERA_TYPE_PATTERNS.items():
            if any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in terms):
                return intent
        return "public_live"

    def _infer_scope(self, target: str) -> str:
        t = target.casefold()
        if "metropolitan" in t or "metro" in t or "greater" in t:
            return "metro"
        if "county" in t:
            return "county"
        if target in US_STATE_NAMES:
            return "state"
        return "place"

    def _infer_admin_hint(self, target: str) -> str | None:
        for n in US_STATE_NAMES:
            if re.search(rf"\b{re.escape(n)}\b", target, re.I):
                return n
        parts = [p.strip() for p in target.split(",")]
        return parts[-1] if len(parts) > 1 else None

    def _strip_scope_words(self, text: str) -> str:
        out = text
        for word in SCOPE_WORDS:
            out = re.sub(rf"\b{re.escape(word)}\b", "", out, flags=re.I)
        return re.sub(r"\s+", " ", out).strip(" ,")



def _looks_like_camera_type_only(value: str) -> bool:
    tokens = {t.casefold() for t in re.findall(r"[A-Za-z0-9]+", value.replace("_", " ")) if t}
    return bool(tokens) and tokens.issubset(CAMERA_TYPE_WORDS)

def _bbox_from_nominatim(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        south, north, west, east = [float(v) for v in raw]
        return {"min_lat": south, "max_lat": north, "min_lon": west, "max_lon": east}
    except Exception:
        return None


def _bbox_plausible(bbox: dict[str, float], scope: str) -> tuple[bool, str]:
    try:
        min_lat, max_lat, min_lon, max_lon = bbox["min_lat"], bbox["max_lat"], bbox["min_lon"], bbox["max_lon"]
    except KeyError:
        return False, "bbox_missing_keys"
    if max_lat <= min_lat or max_lon <= min_lon:
        return False, "bbox_invalid_order"
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90 and -180 <= min_lon <= 180 and -180 <= max_lon <= 180):
        return False, "bbox_coordinate_out_of_range"
    h = abs(max_lat - min_lat) * 69
    mid = math.radians((min_lat + max_lat) / 2)
    w = abs(max_lon - min_lon) * 69 * max(math.cos(mid), 0.05)
    area = w * h
    lower = {"city": 1, "place": 0.01, "county": 20, "metro": 50, "region": 100, "state": 500, "country": 1000}.get(scope, 0.01)
    upper = {"city": 5000, "place": 10000, "county": 25000, "metro": 75000, "region": 250000, "state": 700000, "country": 8000000}.get(scope, 8000000)
    if area < lower:
        return False, "implausibly_small_for_scope_type"
    if area > upper:
        return False, "implausibly_large_for_scope_type"
    return True, "ok"


def _float_or_none(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except Exception:
        return None


def _int_or_none(v: Any) -> int | None:
    try:
        return None if v in (None, "") else int(v)
    except Exception:
        return None


def _tokens(v: str) -> list[str]:
    return [t.casefold() for t in re.findall(r"[A-Za-z0-9]+", v) if len(t) > 2]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        k = v.casefold()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return out


def _slug(value: str, *, default: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return slug[:80] or default
