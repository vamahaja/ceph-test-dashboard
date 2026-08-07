"""Token usage tracking for LLM responses."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class TokenUsage:
    """Accumulated token counts for one agent turn."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    last_total: int = 0
    context_length: int | None = None

    def add(self, prompt: int, completion: int, total: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total
        self.last_total = total

    @property
    def remaining(self) -> int | None:
        if self.context_length is None:
            return None
        return max(0, self.context_length - self.last_total)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["remaining"] = self.remaining
        return data

    def format_caption(self) -> str | None:
        if not self.total_tokens:
            return None
        parts = [f"{self.total_tokens:,} tokens used"]
        remaining = self.remaining
        if remaining is not None:
            parts.append(f"{remaining:,} remaining")
        return " · ".join(parts)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TokenUsage:
        return cls(
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
            last_total=int(
                data.get("last_total") or data.get("total_tokens") or 0
            ),
            context_length=data.get("context_length"),
        )


def usage_from_response(response: Any) -> tuple[int, int, int] | None:
    """Extract (prompt, completion, total) from a completion response or stream chunk."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt = getattr(usage, "prompt_tokens", None) or 0
    completion = getattr(usage, "completion_tokens", None) or 0
    total = getattr(usage, "total_tokens", None) or (prompt + completion)
    if not total and not prompt and not completion:
        return None
    return prompt, completion, total
