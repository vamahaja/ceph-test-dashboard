"""LLM client for the Agent chat page (two-stage intent → answer)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Generator, Iterable
from datetime import date
from typing import Any

from openai import OpenAI, OpenAIError

from libs.config import ConfigError, get_llm_config
from libs.defaults import (
    DEFAULT_LLM_API_KEY,
    DEFAULT_LLM_INTENT_MAX_TOKENS,
    DEFAULT_LLM_MAX_TOKENS,
    DEFAULT_LLM_TIMEOUT,
)
from libs.exceptions import LLMError
from libs.llm.prompts import (
    ANSWER_SYSTEM_PROMPT,
    FORCE_ANSWER_PROMPT,
    INTENT_SYSTEM_PROMPT,
    answer_user_message,
    intent_user_message,
    tool_cache_note,
)
from libs.llm.tools import (
    TOOLS,
    cached_data_blocks,
    call_tool,
    tool_request_cached,
    tool_result_cached,
)
from libs.llm.usage import TokenUsage, usage_from_response

_KNOWN_TOOLS = frozenset(t["function"]["name"] for t in TOOLS)
# Ceph git branches / release codenames — never valid as suite filters.
_CEPH_BRANCHES = frozenset(
    {
        "main",
        "master",
        "tentacle",
        "squid",
        "reef",
        "quincy",
        "pacific",
        "octopus",
        "nautilus",
        "mimic",
        "luminous",
        "kraken",
        "jewel",
    }
)
# Planner aliases → exact Paddles status tokens.
_STATUS_ALIASES = {
    "failed": "fail",
    "failure": "fail",
    "failures": "fail",
    "failing": "fail",
    "passed": "pass",
    "passing": "pass",
    "succeeded": "pass",
    "success": "pass",
    "successful": "pass",
    "timeout": "dead",
    "timedout": "dead",
    "timed_out": "dead",
    "killed": "dead",
}
_VALID_STATUSES = frozenset(
    {"pass", "fail", "dead", "running", "waiting", "queued", "finished"}
)
_PROGRESS_LINE_RE = re.compile(
    r"^_"
    r"(?:Planning|Fetching|Reusing|Cached|Cache hit|Done|Understanding|"
    r"Composing|Finished|Args:|No data|Intent:)"
    r".*?"
    r"_\s*$",
    re.MULTILINE,
)
ProgressCallback = Callable[[str], None]


def is_configured() -> bool:
    """Return True when a valid [llm] section is present in config."""
    try:
        cfg = get_llm_config()
    except (FileNotFoundError, ConfigError):
        return False
    return bool(cfg.get("base_url") and cfg.get("model"))


def _client() -> tuple[OpenAI, str, dict[str, Any]]:
    try:
        cfg = get_llm_config()
    except (FileNotFoundError, ConfigError) as exc:
        raise LLMError(str(exc)) from exc

    timeout = float(cfg.get("timeout") or DEFAULT_LLM_TIMEOUT)
    client = OpenAI(
        base_url=cfg["base_url"].rstrip("/"),
        api_key=cfg.get("api_key") or DEFAULT_LLM_API_KEY,
        timeout=timeout,
    )
    return client, cfg["model"], cfg


def _new_usage(context_length: int | None) -> TokenUsage:
    return TokenUsage(context_length=context_length)


def _configured_max_tokens(cfg: dict[str, Any]) -> int | None:
    """Return configured max_tokens, or None when unset/invalid."""
    value = cfg.get("max_tokens")
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _intent_max_tokens(cfg: dict[str, Any]) -> int | None:
    configured = _configured_max_tokens(cfg)
    if configured is None:
        return DEFAULT_LLM_INTENT_MAX_TOKENS
    return min(configured, DEFAULT_LLM_INTENT_MAX_TOKENS)


def _answer_max_tokens(cfg: dict[str, Any]) -> int | None:
    configured = _configured_max_tokens(cfg)
    return configured if configured is not None else DEFAULT_LLM_MAX_TOKENS


def _record_usage(usage: TokenUsage, response: Any) -> None:
    counts = usage_from_response(response)
    if counts:
        usage.add(*counts)


def _strip_progress(content: str) -> str:
    """Remove streamed progress lines from assistant history sent to the model."""
    cleaned = _PROGRESS_LINE_RE.sub("", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _api_message(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content") or ""
    if message.get("role") == "assistant":
        content = _strip_progress(content)
    return {
        "role": message["role"],
        "content": content,
    }


def _latest_user_text(history: list[dict[str, Any]]) -> str:
    for message in reversed(history):
        if message.get("role") == "user":
            return (message.get("content") or "").strip()
    return ""


def _history_messages(
    history: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prior turns only (exclude the latest user message)."""
    messages = [_api_message(m) for m in history]
    if messages and messages[-1].get("role") == "user":
        return messages[:-1]
    return messages


def _cached_tool_names(tool_cache: dict[str, str] | None) -> list[str]:
    if not tool_cache:
        return []
    return sorted(
        {
            key.split(":", 1)[0]
            for key in tool_cache
            if not key.endswith(":__latest__")
        }
    )


def _single_system_message(*parts: str | None) -> dict[str, Any]:
    """
    Build one leading system message.

    Many chat templates (llama.cpp / HF) reject a second ``system`` role
    anywhere after the first message — including a consecutive system note.
    """
    chunks = [part.strip() for part in parts if part and part.strip()]
    return {"role": "system", "content": "\n\n".join(chunks)}


def _format_tool_args(arguments: str | dict[str, Any] | None) -> str:
    if arguments is None or arguments == "" or arguments == "{}":
        return "none"
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            text = arguments.strip()
            return text if len(text) <= 120 else text[:117] + "…"
    else:
        args = dict(arguments)

    parts: list[str] = []
    for key, value in args.items():
        if value is None or value == "":
            continue
        text = str(value)
        if len(text) > 64:
            text = text[:61] + "…"
        parts.append(f"{key}={text}")
    return ", ".join(parts) if parts else "none"


def _summarize_tool_result(result: str) -> str:
    """Build a short human-readable summary of a tool JSON payload."""
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        text = result.strip()
        return text if len(text) <= 160 else text[:157] + "…"

    if isinstance(data, dict) and data.get("error"):
        return f"error: {data['error']}"

    if isinstance(data, list):
        count = len(data)
        if not count:
            return "0 items"
        preview = data[0]
        if isinstance(preview, str):
            sample = preview if len(preview) <= 48 else preview[:45] + "…"
            return f"{count} name{'s' if count != 1 else ''} (e.g. {sample})"
        if isinstance(preview, dict):
            if "reason" in preview or "failure_reason" in preview:
                top = (
                    preview.get("reason")
                    or preview.get("failure_reason")
                    or "unknown"
                )
                return (
                    f"{count} failure reason{'s' if count != 1 else ''} "
                    f"(top: {top})"
                )
            if "os_type" in preview:
                return f"{count} OS group{'s' if count != 1 else ''}"
            if "suite" in preview or "day" in preview or "date" in preview:
                return f"{count} trend group{'s' if count != 1 else ''}"
            if "name" in preview:
                name = str(preview.get("name") or "")
                sample = name if len(name) <= 48 else name[:45] + "…"
                return (
                    f"{count} testrun{'s' if count != 1 else ''} "
                    f"(e.g. {sample})"
                )
        return f"{count} item{'s' if count != 1 else ''}"

    if isinstance(data, dict):
        if data.get("job_id") is not None and data.get("name") is not None:
            status = data.get("status") or "unknown"
            label = f"job {data.get('job_id')} ({status})"
        elif data.get("name") and ("results" in data or "status" in data):
            name = str(data.get("name") or "")
            sample = name if len(name) <= 48 else name[:45] + "…"
            status = data.get("status") or "unknown"
            label = f"testrun {sample} ({status})"
        elif data.get("result") is None and data.get("note"):
            label = str(data.get("note"))
        elif "testruns" in data and "summary" in data:
            summary = data.get("summary") or {}
            label = (
                f"{data.get('count_returned', len(data.get('testruns') or []))} "
                f"runs, {summary.get('cnt_jobs', '?')} jobs "
                f"({summary.get('cnt_fail', '?')} fail)"
            )
        elif "testrun" in data and isinstance(data.get("testrun"), dict):
            run = data["testrun"]
            name = str(run.get("name") or "")
            sample = name if len(name) <= 40 else name[:37] + "…"
            label = (
                f"report for {sample} "
                f"({data.get('job_count', '?')} jobs, "
                f"{len(data.get('top_failed_jobs') or [])} top failures)"
            )
        elif "jobs" in data and "os_summary" in data:
            label = (
                f"{data.get('job_count', len(data.get('jobs') or []))} jobs, "
                f"{len(data.get('os_summary') or [])} OS groups, "
                f"{len(data.get('top_failure_reasons') or [])} failure reasons"
            )
        elif "cnt_testruns" in data or "cnt_jobs" in data:
            runs = data.get("cnt_testruns")
            jobs = data.get("cnt_jobs")
            fail = data.get("cnt_fail")
            dead = data.get("cnt_dead")
            parts = []
            if runs is not None:
                parts.append(f"{runs} runs")
            if jobs is not None:
                parts.append(f"{jobs} jobs")
            if fail is not None:
                parts.append(f"{fail} fail")
            if dead is not None:
                parts.append(f"{dead} dead")
            label = ", ".join(parts) if parts else "summary ready"
        elif "truncated" in data and "returned" in data:
            label = (
                f"{data.get('returned')} of {data.get('total')} items "
                "(truncated)"
            )
        else:
            keys = ", ".join(list(data.keys())[:5])
            label = f"object with keys: {keys}"
        if data.get("cached"):
            return f"cached · {label}"
        return label

    return type(data).__name__


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from model output."""
    raw = (text or "").strip()
    if not raw:
        return None

    candidates = [raw]
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        candidates.insert(0, fence.group(1))
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def _correct_tool_arguments(args: dict[str, Any]) -> dict[str, Any]:
    """Fix common planner mistakes (branch/suite mixups, status aliases)."""
    corrected = dict(args)
    suite = str(corrected.get("suite") or "").strip()
    branch = str(corrected.get("branch") or "").strip()

    if suite and suite.lower() in _CEPH_BRANCHES and not branch:
        corrected["branch"] = suite
        corrected.pop("suite", None)
    elif suite and suite.lower() in _CEPH_BRANCHES and branch:
        # Suite is clearly a branch name; drop the mistaken suite filter.
        corrected.pop("suite", None)

    status = str(corrected.get("status") or "").strip()
    if status:
        key = status.lower().replace(" ", "_").replace("-", "_")
        if key.startswith("finished_"):
            key = key.split("_", 1)[1]
        normalized = _STATUS_ALIASES.get(key, key)
        if normalized in _VALID_STATUSES:
            corrected["status"] = normalized
        else:
            # Drop unknown status so the packed top_failed_* fields still work.
            corrected.pop("status", None)

    return corrected


def _normalize_plan(raw: dict[str, Any] | None, user_text: str) -> dict[str, Any]:
    """Normalize a stage-1 plan into intent + validated tool requests."""
    if not raw:
        return {
            "intent": user_text or "unknown",
            "needs_data": True,
            "requests": [
                {"tool": "search_testruns", "arguments": {}},
            ],
        }

    intent = str(raw.get("intent") or user_text or "unknown").strip()
    needs_data = bool(raw.get("needs_data", True))
    requests_in = raw.get("requests") or []
    requests: list[dict[str, Any]] = []

    if isinstance(requests_in, dict):
        requests_in = [requests_in]

    for item in requests_in:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool") or item.get("name") or "").strip()
        if name not in _KNOWN_TOOLS:
            continue
        args = item.get("arguments") or item.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        requests.append(
            {
                "tool": name,
                "arguments": _correct_tool_arguments(args),
            }
        )

    if not needs_data:
        requests = []
    elif needs_data and not requests:
        requests = [{"tool": "search_testruns", "arguments": {}}]

    return {
        "intent": intent,
        "needs_data": bool(requests),
        "requests": requests,
    }


def _message_text(message: Any) -> str:
    """Prefer visible content; fall back to reasoning for thinking models."""
    content = (message.content or "").strip()
    if content:
        return content
    reasoning = getattr(message, "reasoning_content", None) or ""
    return str(reasoning).strip()


def _complete(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    *,
    stream: bool = False,
    max_tokens: int | None = DEFAULT_LLM_MAX_TOKENS,
) -> Any:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": stream,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    return client.chat.completions.create(**kwargs)


def _plan_data_requests(
    client: OpenAI,
    model: str,
    history: list[dict[str, Any]],
    usage: TokenUsage,
    *,
    max_tokens: int | None,
    tool_cache: dict[str, str] | None,
) -> dict[str, Any]:
    """Stage 1: ask the model for intent + required data fetches."""
    user_text = _latest_user_text(history)
    today = date.today().isoformat()
    messages: list[dict[str, Any]] = [
        _single_system_message(
            INTENT_SYSTEM_PROMPT,
            f"Today's date is {today}. Use it to resolve relative periods "
            "(last week, July, past 30 days) into period or YYYY-MM-DD "
            "date_start/date_end tool arguments.",
            tool_cache_note(_cached_tool_names(tool_cache)),
        ),
        *_history_messages(history),
        {"role": "user", "content": intent_user_message(user_text)},
    ]

    try:
        response = _complete(
            client,
            model,
            messages,
            stream=False,
            max_tokens=max_tokens,
        )
    except OpenAIError as exc:
        raise LLMError(f"LLM intent planning failed: {exc}") from exc

    _record_usage(usage, response)
    text = _message_text(response.choices[0].message)
    return _normalize_plan(_extract_json_object(text), user_text)


def _fetch_requested_data(
    plan: dict[str, Any],
    *,
    tool_cache: dict[str, str] | None,
    on_progress: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """Execute planned tool requests and return structured data blocks."""
    blocks: list[dict[str, Any]] = []
    for index, request in enumerate(plan.get("requests") or [], start=1):
        name = request["tool"]
        args = request.get("arguments") or {}
        total = len(plan["requests"])
        reuse = tool_request_cached(name, args, tool_cache)
        if on_progress is not None:
            if reuse:
                on_progress(
                    f"Reusing cached `{name}` ({index}/{total})"
                )
            else:
                on_progress(
                    f"Fetching `{name}` ({index}/{total})"
                )
                on_progress(f"Args: {_format_tool_args(args)}")

        payload = call_tool(name, args, cache=tool_cache)
        summary = _summarize_tool_result(payload)
        if on_progress is not None and not reuse:
            if tool_result_cached(payload):
                on_progress(f"Cache hit `{name}` — {summary}")
            else:
                on_progress(f"Done `{name}` — {summary}")
        elif on_progress is not None and reuse:
            on_progress(f"Cached `{name}` — {summary}")

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        if isinstance(data, dict):
            data = {k: v for k, v in data.items() if k != "cached"}

        blocks.append(
            {
                "tool": name,
                "arguments": args,
                "result": data,
                "from_cache": bool(reuse or tool_result_cached(payload)),
            }
        )
    return blocks


def _request_cache_key(request: dict[str, Any]) -> tuple[str, str]:
    args = request.get("arguments") or {}
    if not isinstance(args, dict):
        args = {}
    normalized = {
        key: value
        for key, value in args.items()
        if value is not None and value != ""
    }
    return (
        str(request.get("tool") or ""),
        json.dumps(normalized, sort_keys=True, default=str),
    )


def _partition_requests(
    requests: list[dict[str, Any]],
    tool_cache: dict[str, str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split requests into (already cached, needs fetch)."""
    cached: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for request in requests:
        if tool_request_cached(
            request["tool"],
            request.get("arguments") or {},
            tool_cache,
        ):
            cached.append(request)
        else:
            missing.append(request)
    return cached, missing


def _merge_data_blocks(
    cached_blocks: list[dict[str, Any]],
    fresh_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer freshly fetched blocks; keep other cached blocks for context."""
    ordered: list[dict[str, Any]] = list(fresh_blocks)
    fresh_keys = {_request_cache_key(block) for block in fresh_blocks}
    for block in cached_blocks:
        if _request_cache_key(block) not in fresh_keys:
            ordered.append(block)
    return ordered


def _apply_followup_cache_policy(
    plan: dict[str, Any],
    history: list[dict[str, Any]],
    tool_cache: dict[str, str] | None,
) -> dict[str, Any]:
    """
    Reuse cache for identical follow-up requests; still fetch true misses.

    - needs_data=false → answer from cached blocks
    - every request is an exact cache hit → skip fetch, reuse cache
    - some/all requests miss → fetch only the misses, and keep prior cache
      attached for answer-stage context
    """
    del history  # reserved for future follow-up heuristics
    if not tool_cache:
        return plan

    requests = list(plan.get("requests") or [])
    if not plan.get("needs_data") or not requests:
        return {
            **plan,
            "needs_data": False,
            "requests": [],
            "reuse_cache": True,
        }

    _cached_reqs, missing_reqs = _partition_requests(requests, tool_cache)
    if not missing_reqs:
        return {
            **plan,
            "needs_data": False,
            "requests": [],
            "reuse_cache": True,
        }

    return {
        **plan,
        "needs_data": True,
        "requests": missing_reqs,
        "include_cache": True,
    }


def _resolve_data_blocks(
    plan: dict[str, Any],
    *,
    tool_cache: dict[str, str] | None,
    on_progress: ProgressCallback | None = None,
) -> list[dict[str, Any]]:
    """Fetch missing data and/or rebuild blocks from the conversation cache."""
    fresh: list[dict[str, Any]] = []
    if plan.get("needs_data") and plan.get("requests"):
        fresh = _fetch_requested_data(
            plan,
            tool_cache=tool_cache,
            on_progress=on_progress,
        )

    use_cache = bool(
        tool_cache
        and (
            plan.get("reuse_cache")
            or plan.get("include_cache")
            or (not fresh and not plan.get("needs_data"))
        )
    )
    if not use_cache:
        return fresh

    cached = cached_data_blocks(tool_cache)
    if not fresh:
        return cached
    return _merge_data_blocks(cached, fresh)


def _build_answer_messages(
    history: list[dict[str, Any]],
    *,
    intent: str,
    data_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    user_text = _latest_user_text(history)
    messages: list[dict[str, Any]] = [
        _single_system_message(ANSWER_SYSTEM_PROMPT),
        *_history_messages(history),
        {
            "role": "user",
            "content": answer_user_message(
                user_request=user_text,
                intent=intent,
                data_blocks=data_blocks,
            ),
        },
    ]
    return messages


def _final_text_reply(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    usage: TokenUsage,
    *,
    max_tokens: int | None = DEFAULT_LLM_MAX_TOKENS,
) -> str:
    """Non-streaming final answer."""
    forced = list(messages)
    forced.append({"role": "user", "content": FORCE_ANSWER_PROMPT})
    try:
        response = _complete(
            client,
            model,
            forced,
            stream=False,
            max_tokens=max_tokens,
        )
    except OpenAIError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    _record_usage(usage, response)
    content = _message_text(response.choices[0].message)
    if not content:
        raise LLMError("Unexpected LLM response: empty assistant content")
    return content


def _stream_text(
    client: OpenAI,
    model: str,
    messages: list[dict[str, Any]],
    usage: TokenUsage,
    *,
    max_tokens: int | None = DEFAULT_LLM_MAX_TOKENS,
) -> Generator[str, None, bool]:
    """Stream an assistant reply. Returns True if any content was produced."""
    try:
        stream = _complete(
            client,
            model,
            messages,
            stream=True,
            max_tokens=max_tokens,
        )
    except OpenAIError:
        return False

    produced = False
    try:
        for chunk in stream:
            _record_usage(usage, chunk)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            text = delta.content or getattr(delta, "reasoning_content", None)
            if text:
                produced = True
                yield text
    except OpenAIError:
        return produced
    return produced


def chat(
    messages: list[dict[str, Any]],
    *,
    tool_cache: dict[str, str] | None = None,
) -> tuple[str, TokenUsage]:
    """Two-stage chat: plan data needs, fetch, then answer."""
    client, model, cfg = _client()
    usage = _new_usage(cfg.get("context_length"))
    intent_max_tokens = _intent_max_tokens(cfg)
    answer_max_tokens = _answer_max_tokens(cfg)
    history = list(messages)

    plan = _plan_data_requests(
        client,
        model,
        history,
        usage,
        max_tokens=intent_max_tokens,
        tool_cache=tool_cache,
    )
    plan = _apply_followup_cache_policy(plan, history, tool_cache)
    data_blocks = _resolve_data_blocks(plan, tool_cache=tool_cache)
    answer_messages = _build_answer_messages(
        history,
        intent=plan["intent"],
        data_blocks=data_blocks,
    )
    try:
        response = _complete(
            client,
            model,
            answer_messages,
            stream=False,
            max_tokens=answer_max_tokens,
        )
    except OpenAIError as exc:
        raise LLMError(f"LLM request failed: {exc}") from exc
    _record_usage(usage, response)
    content = _message_text(response.choices[0].message)
    if not content:
        content = _final_text_reply(
            client,
            model,
            answer_messages,
            usage,
            max_tokens=answer_max_tokens,
        )
    return content, usage


def stream_chat(
    messages: list[dict[str, Any]],
    *,
    usage_out: dict[str, Any] | None = None,
    on_progress: ProgressCallback | None = None,
    tool_cache: dict[str, str] | None = None,
) -> Generator[str, None, None]:
    """
    Two-stage streaming chat.

    1. Plan intent + required data fetches (non-streaming).
    2. Fetch all requested tool data.
    3. Stream the final answer with tools disabled.

    Progress updates go to ``on_progress`` when provided; otherwise they are
    yielded inline as markdown before the final answer.
    """
    client, model, cfg = _client()
    intent_max_tokens = _intent_max_tokens(cfg)
    answer_max_tokens = _answer_max_tokens(cfg)
    usage = _new_usage(cfg.get("context_length"))
    history = list(messages)
    inline_progress = on_progress is None

    def _publish_usage() -> None:
        if usage_out is not None and usage.total_tokens:
            usage_out.clear()
            usage_out.update(usage.to_dict())

    def _progress(message: str) -> Generator[str, None, None]:
        if on_progress is not None:
            on_progress(message)
            return
        yield f"_{message}_\n\n"

    yield from _progress("Understanding your question…")
    plan = _plan_data_requests(
        client,
        model,
        history,
        usage,
        max_tokens=intent_max_tokens,
        tool_cache=tool_cache,
    )
    plan = _apply_followup_cache_policy(plan, history, tool_cache)
    yield from _progress(f"Intent: {plan['intent']}")

    data_blocks: list[dict[str, Any]] = []
    if plan.get("needs_data") and plan.get("requests"):
        pending_progress: list[str] = []

        def _collect_progress(message: str) -> None:
            if on_progress is not None:
                on_progress(message)
            else:
                pending_progress.append(message)

        data_blocks = _resolve_data_blocks(
            plan,
            tool_cache=tool_cache,
            on_progress=_collect_progress,
        )
        for message in pending_progress:
            yield f"_{message}_\n\n"
    elif tool_cache and (
        plan.get("reuse_cache") or _cached_tool_names(tool_cache)
    ):
        yield from _progress("Reusing cached data from this chat…")
        data_blocks = cached_data_blocks(tool_cache)
    else:
        yield from _progress("No data fetch required")

    answer_messages = _build_answer_messages(
        history,
        intent=plan["intent"],
        data_blocks=data_blocks,
    )

    yield from _progress("Composing final answer…")
    if inline_progress:
        yield "---\n\n"

    produced = yield from _stream_text(
        client,
        model,
        answer_messages,
        usage,
        max_tokens=answer_max_tokens,
    )
    if produced:
        yield from _progress("Finished")
        _publish_usage()
        return

    # Streaming failed or empty — non-stream fallback.
    content = _final_text_reply(
        client,
        model,
        answer_messages,
        usage,
        max_tokens=answer_max_tokens,
    )
    yield content
    yield from _progress("Finished")
    _publish_usage()
