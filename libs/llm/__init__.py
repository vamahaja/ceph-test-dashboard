"""LLM package: OpenAI-compatible client and Paddles tool wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "TOOLS",
    "call_tool",
    "chat",
    "is_configured",
    "stream_chat",
]

if TYPE_CHECKING:
    from libs.llm.client import chat, is_configured, stream_chat
    from libs.llm.tools import TOOLS, call_tool


def __getattr__(name: str):
    if name in ("TOOLS", "call_tool"):
        from libs.llm.tools import TOOLS, call_tool

        return TOOLS if name == "TOOLS" else call_tool
    if name in ("chat", "is_configured", "stream_chat"):
        from libs.llm.client import chat, is_configured, stream_chat

        return {
            "chat": chat,
            "is_configured": is_configured,
            "stream_chat": stream_chat,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
