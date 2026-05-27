from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class PageDiscoverySignals:
    url: str
    source_provider: str = ""
    source_kind: str = ""
    status_code: int | None = None
    content_type: str = ""
    title: str = ""
    script_count: int = 0
    has_large_script_bundle: bool = False
    dynamic_signals: list[str] | None = None
    json_endpoint_hints: list[str] | None = None
    pagination_hints: list[str] | None = None
    camera_text_score: int = 0
    app_shell_score: int = 0
    has_hls_hint: bool = False
    static_candidate_count: int = 0

    def to_log_record(self, row: dict[str, str], phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "url": self.url,
            "source_provider": self.source_provider,
            "source_kind": self.source_kind,
            "source_name": row.get("source_name") or row.get("title"),
            "status_code": self.status_code,
            "content_type": self.content_type,
            "title": self.title,
            "script_count": self.script_count,
            "has_large_script_bundle": self.has_large_script_bundle,
            "dynamic_signals": self.dynamic_signals or [],
            "json_endpoint_hints": (self.json_endpoint_hints or [])[:20],
            "pagination_hints": (self.pagination_hints or [])[:20],
            "camera_text_score": self.camera_text_score,
            "app_shell_score": self.app_shell_score,
            "has_hls_hint": self.has_hls_hint,
            "static_candidate_count": self.static_candidate_count,
        }

@dataclass
class BrowserCaptureDecision:
    url: str
    source_provider: str
    source_kind: str
    selected: bool
    score: int
    reasons: list[str]
    skip_reason: str = ""
    host: str = ""
    phase: str = "primary"
    source_name: str = ""
    static_candidate_count: int = 0
    budget_remaining: dict[str, int] | None = None
    browser_backend: str = "playwright"

    def to_log_record(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class BrowserCaptureResult:
    url: str
    backend: str = "playwright"
    captured_hls_urls: list[str] | None = None
    captured_json_urls: list[str] | None = None
    rendered_html_candidates: int = 0
    total_browser_candidates: int = 0
    network_events_sample: list[dict[str, Any]] | None = None
    elapsed_ms: int = 0
    timed_out: bool = False
    error: str = ""

    def to_log_record(self, row: dict[str, str], phase: str) -> dict[str, Any]:
        return {
            "phase": phase,
            "url": self.url,
            "backend": self.backend,
            "browser_backend": self.backend,
            "source_provider": row.get("source_provider"),
            "source_kind": row.get("source_kind"),
            "source_name": row.get("source_name") or row.get("title"),
            "elapsed_ms": self.elapsed_ms,
            "captured_hls_urls": len(self.captured_hls_urls or []),
            "captured_json_urls": len(self.captured_json_urls or []),
            "rendered_html_candidates": self.rendered_html_candidates,
            "total_browser_candidates": self.total_browser_candidates,
            "timed_out": self.timed_out,
            "error": self.error,
            "network_events_sample": self.network_events_sample or [],
        }

@dataclass
class BrowserPreflightResult:
    backend: str
    ok: bool
    disabled_reason: str = ""
    install_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def browser_backend_preflight(backend: str) -> BrowserPreflightResult:
    """Check browser backend availability without faking capture success."""
    normalized = (backend or "playwright").strip().casefold()
    if normalized == "cloakbrowser":
        try:
            import cloakbrowser  # type: ignore[import-not-found]
        except Exception as exc:
            return BrowserPreflightResult(
                backend=normalized,
                ok=False,
                disabled_reason=f"cloakbrowser_unavailable: {exc!r}",
                install_hint="Install with: pip install -e .[cloakbrowser]",
            )
        if not hasattr(cloakbrowser, "launch"):
            return BrowserPreflightResult(
                backend=normalized,
                ok=False,
                disabled_reason="cloakbrowser_launch_missing",
                install_hint="Install with: pip install -e .[cloakbrowser]",
            )
        return BrowserPreflightResult(backend=normalized, ok=True)
    if normalized == "playwright":
        try:
            from pathlib import Path
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except Exception as exc:
            return BrowserPreflightResult(
                backend=normalized,
                ok=False,
                disabled_reason=f"playwright_unavailable: {exc!r}",
                install_hint="Install with: pip install -e .[playwright] and run: python -m playwright install chromium",
            )
        try:
            playwright = sync_playwright().start()
            try:
                executable = getattr(playwright.chromium, "executable_path", "")
                if executable and not Path(executable).exists():
                    return BrowserPreflightResult(
                        backend=normalized,
                        ok=False,
                        disabled_reason=f"playwright_chromium_missing: {executable}",
                        install_hint="Run: python -m playwright install chromium",
                    )
            finally:
                playwright.stop()
        except Exception as exc:
            return BrowserPreflightResult(
                backend=normalized,
                ok=False,
                disabled_reason=f"playwright_preflight_failed: {exc!r}",
                install_hint="Install with: pip install -e .[playwright] and run: python -m playwright install chromium",
            )
        return BrowserPreflightResult(backend=normalized, ok=True)
    return BrowserPreflightResult(backend=normalized, ok=False, disabled_reason=f"unsupported_browser_backend:{normalized}")
