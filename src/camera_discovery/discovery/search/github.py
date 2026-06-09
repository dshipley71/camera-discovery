from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx

from camera_discovery.search_queries.github import GITHUB_CODE_SEARCH_QUERIES, GITHUB_WEB_DORK_QUERIES

_GITHUB_CODE_SEARCH_URL = "https://api.github.com/search/code"
_ALLOWED_SOURCE_FILE_SUFFIXES = {
    ".json",
    ".geojson",
    ".csv",
    ".tsv",
    ".yaml",
    ".yml",
    ".xml",
    ".kml",
    ".md",
    ".txt",
    ".js",
    ".ts",
    ".html",
}
_GITHUB_TOKEN_ENV_NAMES = ("CAMERA_DISCOVERY_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")


class GitHubSearchNotConfigured(RuntimeError):
    """Raised when the GitHub provider is selected but cannot authenticate."""


class GitHubSearchRateLimited(RuntimeError):
    """Raised when GitHub reports a rate limit or authorization limit."""


@dataclass(frozen=True)
class GitHubFileReference:
    html_url: str | None
    raw_url: str | None
    owner: str | None
    repo: str | None
    ref: str | None
    path: str | None


def github_token_from_env() -> str:
    """Return a GitHub token using project-specific env precedence without logging it."""

    for name in _GITHUB_TOKEN_ENV_NAMES:
        token = os.getenv(name, "").strip()
        if token:
            return token
    return ""


def github_configured() -> bool:
    return bool(github_token_from_env())


def github_code_queries_for_terms(terms: list[str], max_queries: int) -> list[str]:
    """Build bounded GitHub-native code-search queries from user/target terms.

    The templates are safe public-source discovery patterns. Location/camera-type
    text from existing query expansion is prepended generically; there are no
    hard-coded places or agencies here.
    """

    normalized_terms = _unique_terms(terms)
    templates = [item for item in GITHUB_CODE_SEARCH_QUERIES if item.get("enabled", True)]
    out: list[str] = []
    for term in normalized_terms or [""]:
        for item in templates:
            template = str(item.get("query") or "").strip()
            if not template:
                continue
            query = f"{_quote_term_for_github(term)} {template}".strip() if term else template
            out.append(query)
            if max_queries and len(out) >= max_queries:
                return _dedupe_strings(out)
    return _dedupe_strings(out[:max_queries] if max_queries else out)


def github_web_dork_queries_for_terms(terms: list[str], max_queries: int) -> list[str]:
    """Build GitHub-targeted web dorks for DDG/Bing/SearXNG search backends."""

    normalized_terms = _unique_terms(terms)
    templates = [item for item in GITHUB_WEB_DORK_QUERIES if item.get("enabled", True)]
    out: list[str] = []
    for term in normalized_terms or [""]:
        for item in templates:
            template = str(item.get("query") or "").strip()
            if not template:
                continue
            query = f"{term} {template}".strip() if term else template
            out.append(query)
            if max_queries and len(out) >= max_queries:
                return _dedupe_strings(out)
    return _dedupe_strings(out[:max_queries] if max_queries else out)


def search_github_code(
    query: str,
    *,
    token: str,
    user_agent: str,
    http_timeout: float,
    max_results: int,
) -> list[dict[str, Any]]:
    """Execute a bounded GitHub code search and return normalized source rows."""

    if not token:
        raise GitHubSearchNotConfigured("github_token_not_configured")
    max_results = max(0, int(max_results or 0))
    if max_results <= 0:
        return []
    rows: list[dict[str, Any]] = []
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": user_agent or "camera-discovery",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    per_page = min(100, max_results)
    page = 1
    with httpx.Client(timeout=http_timeout, headers=headers, follow_redirects=True) as client:
        while len(rows) < max_results:
            response = client.get(_GITHUB_CODE_SEARCH_URL, params={"q": query, "per_page": per_page, "page": page})
            if response.status_code in {401, 403}:
                rate_remaining = response.headers.get("x-ratelimit-remaining")
                reason = "github_rate_limited" if rate_remaining == "0" else "github_auth_or_rate_limit_error"
                raise GitHubSearchRateLimited(reason)
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list) or not items:
                break
            rows.extend(rows_from_github_code_items(items, query=query, start_rank=len(rows) + 1))
            if len(rows) >= max_results or len(items) < per_page:
                break
            page += 1
    return rows[:max_results]


def rows_from_github_code_items(items: list[dict[str, Any]], *, query: str, start_rank: int = 1) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for offset, item in enumerate(items):
        path = str(item.get("path") or "").strip()
        if not _is_supported_source_path(path):
            continue
        repo = item.get("repository") if isinstance(item.get("repository"), dict) else {}
        html_url = str(item.get("html_url") or "").strip() or None
        full_name = str(repo.get("full_name") or "").strip()
        owner, repo_name = _split_full_name(full_name)
        default_branch = str(repo.get("default_branch") or "").strip() or None
        ref = parse_github_file_url(html_url or "", known_path=path).ref if html_url else None
        file_ref = GitHubFileReference(
            html_url=html_url,
            raw_url=github_raw_url(owner, repo_name, ref or default_branch, path),
            owner=owner,
            repo=repo_name,
            ref=ref or default_branch,
            path=path,
        )
        source_url = file_ref.raw_url or html_url
        if not source_url:
            continue
        rows.append(
            {
                "url": source_url,
                "title": str(item.get("name") or path or source_url),
                "query": query,
                "snippet": str(item.get("text_matches") or "")[:500],
                "source_kind": "search_result",
                "source_provider": "blind:github",
                "search_engine": "github",
                "source_name": full_name or "github",
                "github_html_url": html_url,
                "github_raw_url": file_ref.raw_url,
                "github_repository": full_name,
                "github_owner": owner,
                "github_repo": repo_name,
                "github_ref": file_ref.ref,
                "github_path": path,
                "github_result_rank": start_rank + offset,
                "github_content_type_hint": _content_type_hint(path),
            }
        )
    return rows


def normalize_github_source_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize GitHub blob/raw URL rows from any backend into fetchable raw files."""

    url = str(row.get("url") or "").strip()
    if not url:
        return row
    file_ref = parse_github_file_url(url, known_path=str(row.get("github_path") or "") or None)
    if not file_ref.raw_url:
        return row
    normalized = dict(row)
    normalized["url"] = file_ref.raw_url
    normalized.setdefault("github_html_url", file_ref.html_url)
    normalized.setdefault("github_raw_url", file_ref.raw_url)
    normalized.setdefault("github_owner", file_ref.owner)
    normalized.setdefault("github_repo", file_ref.repo)
    normalized.setdefault("github_ref", file_ref.ref)
    normalized.setdefault("github_path", file_ref.path)
    if file_ref.owner and file_ref.repo:
        normalized.setdefault("github_repository", f"{file_ref.owner}/{file_ref.repo}")
    return normalized


def parse_github_file_url(url: str, *, known_path: str | None = None) -> GitHubFileReference:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    parts = [part for part in parsed.path.split("/") if part]
    if host == "raw.githubusercontent.com" and len(parts) >= 4:
        owner, repo = parts[0], parts[1]
        file_path_parts = PurePosixPath(known_path).parts if known_path else ()
        if file_path_parts and tuple(parts[-len(file_path_parts):]) == file_path_parts:
            ref = "/".join(parts[2:-len(file_path_parts)])
            path = "/".join(file_path_parts)
        else:
            ref = parts[2]
            path = "/".join(parts[3:])
        return GitHubFileReference(
            html_url=github_html_url(owner, repo, ref, path),
            raw_url=url.split("#", 1)[0],
            owner=owner,
            repo=repo,
            ref=ref,
            path=path,
        )
    if host == "github.com" and len(parts) >= 5 and parts[2] == "blob":
        owner, repo = parts[0], parts[1]
        rest = parts[3:]
        file_path_parts = PurePosixPath(known_path).parts if known_path else ()
        if file_path_parts and tuple(rest[-len(file_path_parts):]) == file_path_parts:
            ref = "/".join(rest[:-len(file_path_parts)])
            path = "/".join(file_path_parts)
        else:
            ref = rest[0]
            path = "/".join(rest[1:])
        raw_url = github_raw_url(owner, repo, ref, path)
        html_url = github_html_url(owner, repo, ref, path)
        return GitHubFileReference(html_url=html_url, raw_url=raw_url, owner=owner, repo=repo, ref=ref, path=path)
    return GitHubFileReference(html_url=None, raw_url=None, owner=None, repo=None, ref=None, path=None)


def github_raw_url(owner: str | None, repo: str | None, ref: str | None, path: str | None) -> str | None:
    if not owner or not repo or not ref or not path:
        return None
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path.lstrip('/')}"


def github_html_url(owner: str | None, repo: str | None, ref: str | None, path: str | None) -> str | None:
    if not owner or not repo or not ref or not path:
        return None
    return f"https://github.com/{owner}/{repo}/blob/{ref}/{path.lstrip('/')}"


def _is_supported_source_path(path: str) -> bool:
    suffix = PurePosixPath(path).suffix.casefold()
    return bool(path) and suffix in _ALLOWED_SOURCE_FILE_SUFFIXES


def _content_type_hint(path: str) -> str:
    suffix = PurePosixPath(path).suffix.casefold().lstrip(".")
    return suffix or "unknown"


def _split_full_name(full_name: str) -> tuple[str | None, str | None]:
    if "/" not in full_name:
        return None, None
    owner, repo = full_name.split("/", 1)
    return owner or None, repo or None


def _unique_terms(terms: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        text = re.sub(r"\s+", " ", str(term or "").strip())
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _quote_term_for_github(term: str) -> str:
    text = term.strip()
    if not text:
        return ""
    if any(ch.isspace() for ch in text):
        return f'"{text.replace(chr(34), "")}"'
    return text


def _dedupe_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = re.sub(r"\s+", " ", value.strip()).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(value.strip())
    return out
