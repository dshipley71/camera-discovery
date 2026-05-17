from __future__ import annotations
import os, httpx
from .base import ChatMessage
class OllamaClient:
    def __init__(self, model: str, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 45.0):
        self.model=model; self.base_url=(base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434").rstrip("/"); self.api_key=api_key if api_key is not None else os.getenv("OLLAMA_API_KEY"); self.timeout=timeout
    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        headers={"Content-Type":"application/json"}
        if self.api_key: headers["Authorization"]=f"Bearer {self.api_key}"
        payload={"model":self.model,"messages":[{"role":m.role,"content":m.content} for m in messages],"stream":False,"options":{"temperature":temperature}}
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            resp=client.post(f"{self.base_url}/api/chat", json=payload); resp.raise_for_status(); data=resp.json()
        return str((data.get("message") or {}).get("content") or data.get("response") or "")
