from __future__ import annotations

import os
from typing import Any

from .base import ChatMessage


class BedrockConverseClient:
    """Amazon Bedrock Runtime Converse API client."""

    def __init__(self, model: str, *, region: str | None = None, timeout: float = 45.0):
        self.model = model
        self.region = region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        self.timeout = timeout
        try:
            import boto3  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Install camera-discovery[bedrock] or boto3 to use Bedrock") from exc
        self.client = boto3.client("bedrock-runtime", region_name=self.region)

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str:
        bedrock_messages: list[dict[str, Any]] = []
        system: list[dict[str, str]] = []
        for message in messages:
            if message.role == "system":
                system.append({"text": message.content})
            else:
                role = message.role if message.role in {"user", "assistant"} else "user"
                bedrock_messages.append({"role": role, "content": [{"text": message.content}]})

        request: dict[str, Any] = {
            "modelId": self.model,
            "messages": bedrock_messages,
            "inferenceConfig": {"temperature": temperature},
        }
        if system:
            request["system"] = system

        response = self.client.converse(**request)
        content = response.get("output", {}).get("message", {}).get("content", [])
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
