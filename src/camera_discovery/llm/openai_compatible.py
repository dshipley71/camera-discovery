from __future__ import annotations
import os, httpx
from .base import ChatMessage
class OpenAICompatibleClient:
    def __init__(self, model: str, *, base_url: str | None = None, api_key: str | None = None, timeout: float = 45.0):
        self.model=model; self.base_url=(base_url or os.getenv("OPENAI_COMPATIBLE_BASE_URL") or "https://api.openai.com/v1").rstrip("/"); self.api_key=api_key if api_key is not None else os.getenv("OPENAI_COMPATIBLE_API_KEY"); self.timeout=timeout
    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        headers={"Content-Type":"application/json"}
        if self.api_key: headers["Authorization"]=f"Bearer {self.api_key}"
        payload={"model":self.model,"messages":[{"role":m.role,"content":m.content} for m in messages],"temperature":temperature}
        with httpx.Client(timeout=self.timeout, headers=headers) as client:
            resp=client.post(f"{self.base_url}/chat/completions", json=payload); resp.raise_for_status(); data=resp.json()
        return str(data["choices"][0]["message"]["content"])
