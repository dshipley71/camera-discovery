from __future__ import annotations

import concurrent.futures
import math
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from camera_discovery.discovery.search.bing import parse_bing_results
from camera_discovery.discovery.search.ddg import parse_ddg_results
from camera_discovery.discovery.search.github import (
    GitHubSearchNotConfigured,
    github_code_queries_for_terms,
    github_configured,
    github_token_from_env,
    github_web_dork_queries_for_terms,
    normalize_github_source_row,
    search_github_code,
)
from camera_discovery.discovery.search.searxng import search_searxng, searxng_enabled
from camera_discovery.extraction.http import _get_with_retry
from camera_discovery.utils.io import write_jsonl

_DDG_URL = "https://duckduckgo.com/html/"
_BING_URL = "https://www.bing.com/search"
_DDG_PAGE_SIZE = 30
_BING_PAGE_SIZE = 10
_DORK_OPERATORS = ("site:", "filetype:", "intitle:", "inurl:")


class SearchDispatcher:
    """Run configured public source-discovery backends (DDG, Bing, SearXNG, GitHub).

    The dispatcher only discovers public source rows. It does not bypass block
    policy, validate media, infer trust, or extract camera URLs from destination
    pages. One engine failure is logged and does not abort other engines.
    """

    def __init__(self, config: Any, source_policy: Any, logs_dir: Path):
        self.config = config
        self.source_policy = source_policy
        self.logs_dir = logs_dir
        self.search_engines = self._configured_engines()
        self.ddg_delay_seconds = float(getattr(config, "ddg_delay_seconds", 1.0) or 0.0)
        self.searxng_base_url = str(getattr(config, "searxng_base_url", "") or "").strip()
        self.searxng_categories = str(getattr(config, "searxng_categories", "general") or "general")
        self.searxng_max_results = int(getattr(config, "searxng_max_results", getattr(config, "max_search_results_per_query", 50)) or 0)
        self._ddg_last_request = 0.0

    def search_all(self, queries: list[str]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
        rows: list[dict[str, str]] = []
        diagnostics: list[dict[str, Any]] = []
        planned_keys: set[str] = set()
        duplicate_suppressed: dict[str, int] = {}
        planned_queries = self._planned_queries_by_engine(queries)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(4, len(self.search_engines)))) as pool:
            tasks: dict[concurrent.futures.Future[list[dict[str, Any]]], dict[str, Any]] = {}
            for engine, engine_queries in planned_queries.items():
                for query in engine_queries:
                    query_type = query_type_for_search_query(query)
                    normalized_query = normalize_search_query(query)
                    if not normalized_query:
                        continue
                    base = _query_attempt_base(engine, query_type, query, normalized_query)
                    query_key = str(base["query_key"])
                    if query_key in planned_keys:
                        duplicate_suppressed[engine] = duplicate_suppressed.get(engine, 0) + 1
                        diagnostics.append(
                            {
                                **base,
                                "configured": True,
                                "attempted": False,
                                "status": "duplicate_suppressed",
                                "results_seen": 0,
                                "parsed_rows": 0,
                                "selected_rows": 0,
                                "blocked_rows": 0,
                                "duplicate_rows": 0,
                                "error_count": 0,
                                "skip_reason": "duplicate_query_attempt",
                                "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                            }
                        )
                        continue
                    planned_keys.add(query_key)
                    if engine == "searxng" and not searxng_enabled(self.searxng_base_url):
                        diagnostics.append(
                            {
                                **base,
                                "configured": False,
                                "attempted": False,
                                "status": "not_configured",
                                "skipped": True,
                                "reason": "searxng_base_url_not_configured",
                                "results_seen": 0,
                                "parsed_rows": 0,
                                "selected_rows": 0,
                                "blocked_rows": 0,
                                "duplicate_rows": 0,
                                "error_count": 0,
                                "skip_reason": "searxng_base_url_not_configured",
                                "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                            }
                        )
                        continue
                    if engine == "github" and not github_configured():
                        diagnostics.append(
                            {
                                **base,
                                "configured": False,
                                "attempted": False,
                                "status": "not_configured",
                                "skipped": True,
                                "reason": "github_token_not_configured",
                                "results_seen": 0,
                                "parsed_rows": 0,
                                "selected_rows": 0,
                                "blocked_rows": 0,
                                "duplicate_rows": 0,
                                "error_count": 0,
                                "skip_reason": "github_token_not_configured",
                                "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                            }
                        )
                        continue
                    if engine == "ddg":
                        tasks[pool.submit(self._ddg_search, query)] = base
                    elif engine == "bing":
                        tasks[pool.submit(self._bing_search, query)] = base
                    elif engine == "searxng":
                        tasks[pool.submit(self._searxng_search, query)] = base
                    elif engine == "github":
                        tasks[pool.submit(self._github_search, query)] = base
            for future in concurrent.futures.as_completed(tasks):
                base = tasks[future]
                engine = str(base["engine"])
                try:
                    engine_rows = future.result()
                    normalized_rows = [normalize_github_source_row(r) for r in engine_rows]
                    filtered = [r for r in normalized_rows if not self.source_policy.block_reason(str(r.get("url") or ""))]
                    for row in filtered:
                        row["query_type"] = base["query_type"]
                        row["normalized_query"] = base["normalized_query"]
                        row["query_key"] = base["query_key"]
                        if base["query_type"] == "dork":
                            row["discovery_query_kind"] = "dork"
                    diagnostics.append(
                        {
                            **base,
                            "configured": True,
                            "attempted": True,
                            "status": "ran",
                            "results_seen": len(engine_rows),
                            "parsed_rows": len(engine_rows),
                            "selected_rows": len(filtered),
                            "blocked_rows": max(0, len(engine_rows) - len(filtered)),
                            "duplicate_rows": max(0, len(normalized_rows) - len(self._dedupe_rows(normalized_rows))),
                            "error_count": 0,
                            "skip_reason": None,
                            "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                        }
                    )
                    rows.extend(filtered)  # type: ignore[arg-type]
                except Exception as exc:
                    diagnostics.append(
                        {
                            **base,
                            "configured": True,
                            "attempted": True,
                            "status": "error",
                            "error": repr(exc),
                            "results_seen": 0,
                            "parsed_rows": 0,
                            "selected_rows": 0,
                            "blocked_rows": 0,
                            "duplicate_rows": 0,
                            "error_count": 1,
                            "skip_reason": repr(exc)[:300],
                            "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                        }
                    )
        if diagnostics:
            diagnostics.append(
                {
                    "record_type": "query_plan_summary",
                    "total_query_attempts": len([d for d in diagnostics if d.get("query_key")]),
                    "unique_query_attempts": len(planned_keys),
                    "duplicate_query_attempts_suppressed": sum(duplicate_suppressed.values()),
                    "duplicate_query_attempts_suppressed_by_engine": dict(sorted(duplicate_suppressed.items())),
                    "unique_query_texts": len({str(d.get("normalized_query") or "") for d in diagnostics if d.get("normalized_query")}),
                    "dork_queries_enabled": any(d.get("query_type") == "dork" for d in diagnostics),
                    "diagnostics_path": "logs/search_engine_diagnostics.jsonl",
                }
            )
            write_jsonl(self.logs_dir / "search_engine_diagnostics.jsonl", diagnostics)
        return self._dedupe_rows(rows), diagnostics

    def _configured_engines(self) -> list[str]:
        raw = getattr(self.config, "search_engines", None) or ["ddg", "bing", "searxng"]
        if isinstance(raw, str):
            engines = [p.strip().casefold() for p in raw.split(",") if p.strip()]
        else:
            engines = [str(p).strip().casefold() for p in raw if str(p).strip()]
        valid = [e for e in engines if e in {"ddg", "bing", "searxng", "github"}]
        if not valid:
            valid = ["ddg", "bing", "searxng"]
        return list(dict.fromkeys(valid))


    def _planned_queries_by_engine(self, queries: list[str]) -> dict[str, list[str]]:
        base_queries = list(queries)
        planned: dict[str, list[str]] = {engine: list(base_queries) for engine in self.search_engines if engine != "github"}
        if "github" in self.search_engines:
            github_max_queries = int(getattr(self.config, "github_max_queries", getattr(self.config, "max_search_queries", 12)) or 0)
            planned["github"] = github_code_queries_for_terms(base_queries, max_queries=github_max_queries)
            web_dork_max = int(getattr(self.config, "github_web_dork_max_queries", github_max_queries) or 0)
            web_dorks = github_web_dork_queries_for_terms(base_queries, max_queries=web_dork_max)
            for engine in ("ddg", "bing", "searxng"):
                if engine in planned:
                    planned[engine] = [*planned[engine], *web_dorks]
        return planned

    def _ddg_search(self, query: str) -> list[dict[str, Any]]:
        max_results = int(getattr(self.config, "max_search_results_per_query", 50) or 0)
        pages = max(1, math.ceil(max_results / _DDG_PAGE_SIZE)) if max_results else 0
        out: list[dict[str, Any]] = []
        for page in range(pages):
            elapsed = time.monotonic() - self._ddg_last_request
            if elapsed < self.ddg_delay_seconds:
                time.sleep(self.ddg_delay_seconds - elapsed)
            params = {"q": query}
            if page:
                params["s"] = str(page * _DDG_PAGE_SIZE)
            with httpx.Client(timeout=getattr(self.config, "http_timeout", 20.0), headers={"User-Agent": getattr(self.config, "user_agent", "camera-discovery")}, follow_redirects=True) as client:
                response = _get_with_retry(client, _DDG_URL + "?" + urlencode(params))
                response.raise_for_status()
            self._ddg_last_request = time.monotonic()
            page_rows = parse_ddg_results(response.text, query=query, max_results=max_results - len(out))
            out.extend(page_rows)
            if not page_rows or len(out) >= max_results:
                break
        return out[:max_results]

    def _bing_search(self, query: str) -> list[dict[str, Any]]:
        max_results = int(getattr(self.config, "max_search_results_per_query", 50) or 0)
        pages = max(1, math.ceil(max_results / _BING_PAGE_SIZE)) if max_results else 0
        out: list[dict[str, Any]] = []
        for page in range(pages):
            params = {"q": query}
            if page:
                params["first"] = str(page * _BING_PAGE_SIZE)
            with httpx.Client(timeout=getattr(self.config, "http_timeout", 20.0), headers={"User-Agent": getattr(self.config, "user_agent", "camera-discovery")}, follow_redirects=True) as client:
                response = client.get(_BING_URL, params=params)
                response.raise_for_status()
            page_rows = parse_bing_results(response.text, query=query, max_results=max_results - len(out))
            out.extend(page_rows)
            if len(page_rows) < _BING_PAGE_SIZE or len(out) >= max_results:
                break
        return out[:max_results]

    def _searxng_search(self, query: str) -> list[dict[str, Any]]:
        return search_searxng(
            query,
            base_url=self.searxng_base_url,
            user_agent=getattr(self.config, "user_agent", "camera-discovery"),
            http_timeout=float(getattr(self.config, "http_timeout", 20.0)),
            categories=self.searxng_categories,
            max_results=self.searxng_max_results or int(getattr(self.config, "max_search_results_per_query", 50) or 50),
        )


    def _github_search(self, query: str) -> list[dict[str, Any]]:
        token = github_token_from_env()
        if not token:
            raise GitHubSearchNotConfigured("github_token_not_configured")
        return search_github_code(
            query,
            token=token,
            user_agent=getattr(self.config, "user_agent", "camera-discovery"),
            http_timeout=float(getattr(self.config, "http_timeout", 20.0)),
            max_results=int(getattr(self.config, "github_max_results", getattr(self.config, "max_search_results_per_query", 50)) or 0),
        )

    @staticmethod
    def _dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for row in rows:
            row = normalize_github_source_row(row)
            url = str(row.get("url") or "").split("#", 1)[0]
            if not url.startswith(("http://", "https://")):
                continue
            existing = merged.get(url)
            if existing is None:
                copied = {str(k): v for k, v in row.items() if v not in (None, "", [], {})}
                copied["url"] = url
                copied.setdefault("source_kind", "search_result")
                copied.setdefault("source_provider", f"blind:{copied.get('search_engine', 'search')}")
                existing_engines = copied.get("search_engines") if isinstance(copied.get("search_engines"), list) else None
                copied["search_engines"] = existing_engines or ([copied.get("search_engine")] if copied.get("search_engine") else [])
                merged[url] = copied
                order.append(url)
                continue
            engine = row.get("search_engine")
            engines = existing.setdefault("search_engines", [])
            if engine and engine not in engines:
                engines.append(engine)
                existing["source_provider"] = "blind:multi"
            if row.get("query_type") == "dork" or existing.get("query_type") == "dork":
                existing["query_type"] = "dork"
                existing["discovery_query_kind"] = "dork"
        return [{str(k): v for k, v in merged[url].items()} for url in order]


def normalize_search_query(query: str) -> str:
    text = str(query or "").strip()
    text = text.translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"}))
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def query_type_for_search_query(query: str) -> str:
    lowered = str(query or "").casefold()
    return "dork" if any(op in lowered for op in _DORK_OPERATORS) else "normal"


def _query_attempt_base(engine: str, query_type: str, query: str, normalized_query: str) -> dict[str, Any]:
    query_key = f"{engine}|{query_type}|{normalized_query}"
    return {
        "engine": engine,
        "query_type": query_type,
        "query": query,
        "normalized_query": normalized_query,
        "query_key": query_key,
    }
