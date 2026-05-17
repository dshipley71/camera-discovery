from __future__ import annotations

import re
from dataclasses import asdict
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from camera_discovery.core.models import CameraCandidate, CandidateSet, DiscoveryMode, RunConfig, TargetContext
from camera_discovery.llm.base import ChatMessage, LLMClient
from camera_discovery.llm.factory import build_candidate_review_client
from camera_discovery.sources import SourceEntry, SourcePolicy, load_source_policy
from camera_discovery.utils.io import write_json, write_jsonl
from camera_discovery.utils.json_utils import extract_json_object

M3U8_RE = re.compile(r"https?://[^\s'\"<>]+?\.m3u8(?:\?[^\s'\"<>]*)?|['\"]([^'\"]+?\.m3u8(?:\?[^'\"]*)?)['\"]", re.I)
COORD_RE = re.compile(r"(?<!\d)([-+]?\d{1,2}\.\d{3,})\s*,\s*([-+]?\d{1,3}\.\d{3,})(?!\d)")


class DirectorySourceProvider:
    """Expose user-approved directory sources from SOURCES.md as discovery inputs."""

    def __init__(self, policy: SourcePolicy):
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for entry in self.policy.enabled_allowed_sources():
            if self.policy.is_blocked(entry.url):
                continue
            rows.append(_row_from_source_entry(entry, target))
        return rows


class DirectUrlSourceProvider:
    """Expose command-line seed URLs as discovery inputs while respecting global block rules."""

    def __init__(self, urls: list[str], policy: SourcePolicy):
        self.urls = urls
        self.policy = policy

    def rows_for_target(self, target: TargetContext) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for url in self.urls:
            if self.policy.is_blocked(url):
                continue
            entry = SourceEntry(name=url, url=url, source_type="direct_hls" if _looks_like_hls(url) else "page")
            rows.append(_row_from_source_entry(entry, target, provider="direct"))
        return rows


class CandidateDiscoveryEngine:
    """Discover candidates while keeping source allow-lists and block rules deterministic.

    Blind search, directory sources, and direct URLs are discovery inputs inside this
    service. Global block rules from SOURCES.md apply to every mode, including blind
    search, directory mode, and direct seed URLs.
    """

    def __init__(self, config: RunConfig, semantic_review_client: LLMClient | None = None):
        self.config = config
        self.semantic_review_client = semantic_review_client
        self.logs_dir = config.output_dir / "logs"
        self.candidates_dir = config.output_dir / "candidates"
        self.source_policy = load_source_policy(config.sources_file, config.block_patterns)
        self.directory_provider = DirectorySourceProvider(self.source_policy)
        self.direct_provider = DirectUrlSourceProvider(config.seed_urls, self.source_policy)

    def discover(self, target: TargetContext) -> CandidateSet:
        queries = self._search_queries(target) if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH} else []
        results = self._source_rows(target, queries)
        raw: list[CameraCandidate] = []
        for row in self._select_rows(results)[: self.config.max_pages]:
            raw.extend(self._extract_from_source_row(row))
            if len(raw) >= self.config.max_streams:
                break
        raw = raw[: self.config.max_streams]
        unique = self._dedupe(raw)
        self._scope_candidates(unique, target)
        self._apply_llm_candidate_review(unique, target)
        for c in raw:
            c.target_id = target.target_id
            c.target_index = target.target_index
            c.target_label = target.target_label or target.canonical_target
        for c in unique:
            c.target_id = target.target_id
            c.target_index = target.target_index
            c.target_label = target.target_label or target.canonical_target
        cs = self._build_candidate_set(raw, unique)
        self._write_artifacts(queries, results, cs, target)
        return cs

    def _source_rows(self, target: TargetContext, queries: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        if self.config.discovery_mode in {DiscoveryMode.BLIND, DiscoveryMode.BOTH}:
            rows.extend(self._blind_search(queries))
        if self.config.discovery_mode in {DiscoveryMode.DIRECTORY, DiscoveryMode.BOTH}:
            rows.extend(self.directory_provider.rows_for_target(target))
        if self.config.seed_urls and self.config.discovery_mode in {DiscoveryMode.DIRECT, DiscoveryMode.BOTH, DiscoveryMode.BLIND, DiscoveryMode.DIRECTORY}:
            rows.extend(self.direct_provider.rows_for_target(target))
        return rows

    def _build_candidate_set(self, raw: list[CameraCandidate], unique: list[CameraCandidate]) -> CandidateSet:
        return CandidateSet(
            raw=raw,
            unique=unique,
            coordinate_bearing=[c for c in unique if c.has_coordinates],
            in_scope=[c for c in unique if c.scope_status == "in_scope"],
            review=[c for c in unique if c.scope_status in {"review", "unknown", "in_scope"}],
            rejected=[c for c in unique if c.scope_status == "out_of_scope"],
        )

    def _search_queries(self, target: TargetContext) -> list[str]:
        base = target.canonical_target or target.user_query
        return [
            f"{base} public live cameras m3u8",
            f"{base} traffic cameras live stream",
            f"{base} webcam HLS",
            f"{base} public cameras live",
        ][: self.config.max_search_queries]

    def _blind_search(self, queries: list[str]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
            for query in queries:
                try:
                    resp = client.get(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
                    resp.raise_for_status()
                    rows.extend(self._parse_ddg(query, resp.text))
                except Exception as exc:
                    rows.append({"query": query, "url": "", "title": "", "error": repr(exc), "source_provider": "blind"})
        return rows

    def _parse_ddg(self, query: str, html: str) -> list[dict[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict[str, str]] = []
        for anchor in soup.select("a.result__a")[: self.config.max_search_results_per_query]:
            url = self._clean(anchor.get("href") or "")
            if url:
                results.append({"query": query, "title": anchor.get_text(" ", strip=True), "url": url, "snippet": "", "source_provider": "blind"})
        return results

    def _clean(self, href: str) -> str:
        if not href:
            return ""
        if "duckduckgo.com/l/" in href or href.startswith("//duckduckgo.com/l/"):
            parsed = urlparse(href if href.startswith("http") else "https:" + href)
            return unquote(parse_qs(parsed.query).get("uddg", [""])[0])
        return href

    def _select_rows(self, rows: list[dict[str, str]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        selected: list[dict[str, str]] = []
        blocked_rows: list[dict[str, str]] = []
        for row in rows:
            url = row.get("url") or ""
            key = url.split("#", 1)[0]
            if not url.startswith("http") or key in seen:
                continue
            reason = self.source_policy.block_reason(url)
            if reason:
                blocked = dict(row)
                blocked["blocked_reason"] = reason
                blocked_rows.append(blocked)
                continue
            seen.add(key)
            selected.append({**row, "url": key})
        write_jsonl(self.logs_dir / "blocked_source_rows.jsonl", blocked_rows)
        return selected

    def _extract_from_source_row(self, row: dict[str, str]) -> list[CameraCandidate]:
        url = row.get("url") or ""
        if self.source_policy.is_blocked(url):
            return []
        if _looks_like_hls(url):
            return [self._candidate_from_stream(url, url, row, "direct_hls")]
        return self._extract_from_page(url, row)

    def _extract_from_page(self, url: str, row: dict[str, str]) -> list[CameraCandidate]:
        try:
            with httpx.Client(timeout=self.config.http_timeout, headers={"User-Agent": self.config.user_agent}, follow_redirects=True) as client:
                resp = client.get(url)
                resp.raise_for_status()
                text = resp.text
        except Exception:
            return []
        coords = self._extract_first_coord(text)
        out: list[CameraCandidate] = []
        for match in M3U8_RE.finditer(text):
            raw = match.group(0).strip("'\"") if match.group(0).startswith("http") else (match.group(1) or "").strip("'\"")
            stream = urljoin(url, raw)
            if ".m3u8" in stream.lower() and not self.source_policy.is_blocked(stream):
                candidate = self._candidate_from_stream(stream, url, row, "page_regex")
                if coords:
                    candidate.lat, candidate.lon = coords
                out.append(candidate)
        return out

    def _candidate_from_stream(self, stream_url: str, source_url: str, row: dict[str, str], method: str) -> CameraCandidate:
        metadata = {
            "source_provider": row.get("source_provider"),
            "source_kind": row.get("source_kind"),
            "source_name": row.get("source_name"),
            "source_scope_hint": row.get("source_scope_hint"),
            "source_notes": row.get("source_notes"),
            "query": row.get("query"),
        }
        return CameraCandidate(
            stream_url=stream_url,
            source_url=source_url,
            discovery_method=method,
            title=row.get("title") or row.get("source_name"),
            source_metadata={k: v for k, v in metadata.items() if v},
        )

    def _extract_first_coord(self, text: str) -> tuple[float, float] | None:
        for match in COORD_RE.finditer(text):
            lat, lon = float(match.group(1)), float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return lat, lon
        return None

    def _dedupe(self, rows: list[CameraCandidate]) -> list[CameraCandidate]:
        seen: set[str] = set()
        out: list[CameraCandidate] = []
        for row in rows:
            key = row.stream_url.split("#", 1)[0]
            if key not in seen:
                seen.add(key)
                out.append(row)
        return out

    def _scope_candidates(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        bbox = target.bbox if target.bbox_verified else None
        for candidate in candidates:
            if candidate.has_coordinates and bbox:
                if bbox["min_lat"] <= candidate.lat <= bbox["max_lat"] and bbox["min_lon"] <= candidate.lon <= bbox["max_lon"]:
                    candidate.scope_status = "in_scope"
                    candidate.reasons.append("coordinate_inside_verified_bbox")
                else:
                    candidate.scope_status = "out_of_scope"
                    candidate.trust_level = "rejected"
                    candidate.reasons.append("coordinate_outside_verified_bbox")
            elif candidate.has_coordinates:
                candidate.scope_status = "review"
                candidate.reasons.append("coordinate_available_but_target_bbox_untrusted_or_missing")
            else:
                candidate.scope_status = "unknown"
                candidate.reasons.append("missing_candidate_coordinates")

    def _apply_llm_candidate_review(self, candidates: list[CameraCandidate], target: TargetContext) -> None:
        if not candidates:
            return
        client = self.semantic_review_client or build_candidate_review_client(self.config)
        reviewable = [candidate for candidate in candidates if not (candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected")][:50]
        if not reviewable:
            return
        payload = [
            {
                "index": candidates.index(candidate),
                "stream_url": candidate.stream_url,
                "source_url": candidate.source_url,
                "title": candidate.title,
                "lat": candidate.lat,
                "lon": candidate.lon,
                "location_text": candidate.location_text,
                "deterministic_scope_status": candidate.scope_status,
                "reasons": candidate.reasons,
                "source_metadata": candidate.source_metadata,
            }
            for candidate in reviewable
        ]
        raw = client.chat(
            [
                ChatMessage("system", "Return strict JSON only. You are an advisory semantic reviewer, not a stream validator."),
                ChatMessage("user", self._candidate_review_prompt(target, payload)),
            ],
            temperature=0.0,
        )
        data = extract_json_object(raw)
        write_json(self.logs_dir / "candidate_semantic_review_llm_raw.json", {"raw": raw, "model": getattr(client, "model", None)})
        write_json(self.logs_dir / "candidate_semantic_review.json", data)
        rows = data.get("candidates") if isinstance(data.get("candidates"), list) else []
        by_index = {index: candidate for index, candidate in enumerate(candidates)}
        for row in rows:
            if not isinstance(row, dict):
                continue
            index = _int_or_none(row.get("index"))
            if index is None or index not in by_index:
                continue
            candidate = by_index[index]
            decision = str(row.get("decision") or "review").casefold()
            if decision not in {"in_scope", "out_of_scope", "review", "unknown"}:
                decision = "review"
            candidate.llm_semantic_decision = decision  # type: ignore[assignment]
            candidate.llm_semantic_confidence = _float_or_none(row.get("confidence"))
            candidate.llm_semantic_reason = str(row.get("reason") or "")[:500]
            candidate.reasons.append(f"llm_semantic_review:{decision}")
            if candidate.scope_status == "out_of_scope" and candidate.trust_level == "rejected":
                continue
            if decision == "out_of_scope" and (candidate.llm_semantic_confidence or 0.0) >= 0.75:
                candidate.scope_status = "out_of_scope"
                candidate.trust_level = "rejected"
            elif decision == "in_scope" and target.bbox_verified and candidate.has_coordinates:
                if candidate.scope_status != "out_of_scope":
                    candidate.scope_status = "in_scope"
            elif decision in {"in_scope", "review"} and candidate.scope_status == "unknown":
                candidate.scope_status = "review"

    def _candidate_review_prompt(self, target: TargetContext, candidates: list[dict]) -> str:
        return (
            "Review candidate public-camera HLS streams semantically against the target context. "
            "Use source_url/title/coordinates/location text only as evidence. Do not validate whether streams are live, reachable, or decoded. "
            "Do not authorize trusted output. Return JSON: {\"candidates\":[{\"index\":0,\"decision\":\"in_scope|out_of_scope|review|unknown\","
            "\"confidence\":0.0,\"reason\":\"short reason\"}]}\n"
            f"Target: canonical={target.canonical_target!r}, scope={target.scope_type!r}, admin={target.admin_region!r}, country={target.country!r}, bbox_verified={target.bbox_verified}\n"
            f"Candidates: {candidates}"
        )

    def _write_artifacts(self, queries: list[str], results: list[dict], cs: CandidateSet, target: TargetContext) -> None:
        target_logs = self.logs_dir / "targets" / target.target_id
        target_candidates = self.candidates_dir / target.target_id
        write_json(target_logs / "source_policy_summary.json", self.source_policy.to_dict())
        write_json(self.logs_dir / "source_policy_summary.json", self.source_policy.to_dict())
        write_json(target_logs / "search_queries.json", {"target_id": target.target_id, "queries": queries})
        write_jsonl(target_logs / "search_results.jsonl", results)
        write_jsonl(target_candidates / "agentic_candidates.jsonl", [asdict(candidate) for candidate in cs.raw])
        write_jsonl(target_candidates / "agentic_candidates_unique.jsonl", [asdict(candidate) for candidate in cs.unique])
        summary = {
            "target_id": target.target_id,
            "target_label": target.target_label,
            "discovery_mode": self.config.discovery_mode.value,
            "sources_file": str(self.config.sources_file) if self.config.sources_file else None,
            "allowed_directory_sources": len(self.source_policy.enabled_allowed_sources()),
            "blocked_patterns": len(self.source_policy.blocked_sources),
            "raw": len(cs.raw),
            "unique": len(cs.unique),
            "coordinate_bearing": len(cs.coordinate_bearing),
            "in_scope": len(cs.in_scope),
            "review": len(cs.review),
            "rejected": len(cs.rejected),
            "llm_semantic_reviewed": sum(1 for candidate in cs.unique if candidate.llm_semantic_decision),
        }
        write_json(target_logs / "candidate_discovery_summary.json", summary)
        if target.target_index == 0:
            write_json(self.logs_dir / "search_queries.json", {"queries": queries})
            write_jsonl(self.logs_dir / "search_results.jsonl", results)
            write_jsonl(self.candidates_dir / "agentic_candidates.jsonl", [asdict(candidate) for candidate in cs.raw])
            write_jsonl(self.candidates_dir / "agentic_candidates_unique.jsonl", [asdict(candidate) for candidate in cs.unique])
            write_json(self.logs_dir / "candidate_discovery_summary.json", summary)


def _row_from_source_entry(entry: SourceEntry, target: TargetContext, provider: str = "directory") -> dict[str, str]:
    return {
        "query": f"{provider}:{target.target_id}",
        "title": entry.name,
        "url": entry.url,
        "snippet": entry.notes or "",
        "source_provider": provider,
        "source_kind": entry.source_type,
        "source_name": entry.name,
        "source_scope_hint": entry.scope_hint or "",
        "source_notes": entry.notes or "",
    }


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
