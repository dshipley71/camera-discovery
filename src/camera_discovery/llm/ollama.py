from __future__ import annotations

import os
from typing import Any

import httpx

from .base import ChatMessage


class OllamaClient:
    def __init__(self, model: str, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 45.0):
        self.model = model
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("OLLAMA_API_KEY")
        self.timeout = timeout

    def _api_url(self, path: str) -> str:
        clean_path = "/" + path.lstrip("/")
        if self.base_url.endswith("/api"):
            return f"{self.base_url}{clean_path}"
        return f"{self.base_url}/api{clean_path}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        with httpx.Client(timeout=self.timeout, headers=self._headers()) as client:
            resp = client.post(self._api_url("/chat"), json=payload)
            resp.raise_for_status()
            data = resp.json()
        return str((data.get("message") or {}).get("content") or data.get("response") or "")

    def preflight(self) -> dict[str, Any]:
        """Verify that the configured Ollama-compatible endpoint and model work.

        The check intentionally performs a tiny real chat request. A tags-only
        check can succeed against the wrong host or with a model that cannot
        actually run; the chat probe catches the 404/401 cases before the middle
        of a discovery run.
        """
        status: dict[str, Any] = {
            "provider": "ollama",
            "model": self.model,
            "base_url": self.base_url,
            "api_base_url": self._api_url(""),
            "ok": False,
            "auth_configured": bool(self.api_key),
        }
        if "ollama.com" in self.base_url.casefold() and not self.api_key:
            status.update(
                {
                    "error_type": "missing_api_key",
                    "error": "OLLAMA_API_KEY is required for direct Ollama Cloud API access.",
                }
            )
            return status
        try:
            with httpx.Client(timeout=min(float(self.timeout), 20.0), headers=self._headers()) as client:
                tags_resp = client.get(self._api_url("/tags"))
                status["tags_status_code"] = tags_resp.status_code
                if tags_resp.status_code < 400:
                    try:
                        tags = tags_resp.json().get("models", [])
                    except Exception:
                        tags = []
                    model_names = [str(item.get("name") or item.get("model") or "") for item in tags if isinstance(item, dict)]
                    if model_names:
                        status["available_models_sample"] = model_names[:20]
                        status["model_listed"] = self.model in model_names
                payload = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": "Return exactly: ok"}],
                    "stream": False,
                    "options": {"temperature": 0},
                }
                chat_resp = client.post(self._api_url("/chat"), json=payload)
                status["chat_status_code"] = chat_resp.status_code
                if chat_resp.status_code >= 400:
                    status["error_type"] = "http_error"
                    status["error"] = chat_resp.text[:1000]
                    return status
                data = chat_resp.json()
                status["ok"] = bool((data.get("message") or {}).get("content") or data.get("response"))
                if not status["ok"]:
                    status["error_type"] = "empty_response"
                    status["error"] = "Endpoint responded but returned no model content."
                return status
        except Exception as exc:
            status["error_type"] = type(exc).__name__
            status["error"] = str(exc)[:1000]
            return status
