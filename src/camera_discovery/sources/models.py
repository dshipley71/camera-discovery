from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

SourceType = Literal["page", "feed", "direct_hls", "site", "dynamic"]


@dataclass
class SourceEntry:
    name: str
    url: str
    source_type: SourceType = "page"
    scope_hint: str | None = None
    enabled: bool = True
    notes: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BlockedSource:
    pattern: str
    reason: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SourcePolicy:
    allowed_sources: list[SourceEntry] = field(default_factory=list)
    blocked_sources: list[BlockedSource] = field(default_factory=list)
    source_file: Path | None = None

    def enabled_allowed_sources(self) -> list[SourceEntry]:
        return [entry for entry in self.allowed_sources if entry.enabled and entry.url]

    def is_blocked(self, url: str | None) -> bool:
        return self.block_reason(url) is not None

    def block_reason(self, url: str | None) -> str | None:
        if not url:
            return None
        parsed = urlparse(url)
        host = (parsed.netloc or "").casefold()
        normalized_url = url.casefold()
        for blocked in self.blocked_sources:
            pattern = blocked.pattern.strip().casefold()
            if not pattern:
                continue
            if _matches_pattern(pattern, host, normalized_url):
                return blocked.reason or f"blocked_by_pattern:{blocked.pattern}"
        return None

    def filter_urls(self, urls: list[str]) -> list[str]:
        return [url for url in urls if not self.is_blocked(url)]

    def to_dict(self) -> dict:
        return {
            "source_file": str(self.source_file) if self.source_file else None,
            "allowed_sources": [entry.to_dict() for entry in self.allowed_sources],
            "blocked_sources": [entry.to_dict() for entry in self.blocked_sources],
            "enabled_allowed_sources": len(self.enabled_allowed_sources()),
        }


def _matches_pattern(pattern: str, host: str, normalized_url: str) -> bool:
    if pattern.startswith("http://") or pattern.startswith("https://"):
        return fnmatch(normalized_url, pattern) or normalized_url.startswith(pattern.rstrip("*"))
    if "/" in pattern:
        return fnmatch(normalized_url, f"*{pattern}*")
    if pattern.startswith("*."):
        suffix = pattern[1:]
        return host.endswith(suffix) or fnmatch(host, pattern)
    return host == pattern or host.endswith("." + pattern) or fnmatch(host, pattern)
