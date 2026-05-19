from __future__ import annotations

import os
from urllib.parse import urljoin

import httpx

from .base import ChatMessage


class OllamaClient:
    def __init__(self, model: str, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 45.0):
        self.model = model
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("OLLAMA_API_KEY")
        self.timeout = timeout

    def _api_url(self, path: str) -> str:
        normalized_path = "/" + path.lstrip("/")
        base = self.base_url.rstrip("/")
        if base.endswith("/api"):
            return base + normalized_path
        return base + "/api" + normalized_path

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def preflight(self) -> dict[str, object]:
        """Run a small real provider check before a long discovery run."""
        if "ollama.com" in self.base_url.casefold() and not self.api_key:
            return {"ok": False, "provider": "ollama", "model": self.model, "error_type": "missing_api_key", "error": "OLLAMA_API_KEY is required for Ollama Cloud"}
        try:
            response = self.chat([ChatMessage("user", "Return the word ok.")], temperature=0.0)
        except Exception as exc:
            return {"ok": False, "provider": "ollama", "model": self.model, "error_type": exc.__class__.__name__, "error": repr(exc), "base_url": self.base_url}
        return {"ok": bool(str(response).strip()), "provider": "ollama", "model": self.model, "base_url": self.base_url}

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
