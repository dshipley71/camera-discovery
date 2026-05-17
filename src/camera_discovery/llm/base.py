from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChatMessage:
    role: str
    content: str


class LLMClient(Protocol):
    model: str

    def chat(self, messages: list[ChatMessage], *, temperature: float = 0.0) -> str: ...
