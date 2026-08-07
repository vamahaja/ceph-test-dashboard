import streamlit as st

from libs.exceptions import LLMError
from libs.llm import is_configured, stream_chat
from libs.llm.usage import TokenUsage

st.markdown(
    "<h1 style='text-align: center;'>Agent</h1>",
    unsafe_allow_html=True,
)

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []
if "agent_tool_cache" not in st.session_state:
    st.session_state.agent_tool_cache = {}

_, clear_col = st.columns([5, 1])
with clear_col:
    if st.button("Clear chat", use_container_width=True):
        st.session_state.agent_messages = []
        st.session_state.agent_tool_cache = {}
        st.rerun()

if not is_configured():
    st.info(
        "The agent can't answer yet — add an `[llm]` section to your "
        "config (`base_url`, `model`, and optional `api_key` / `api_token`)."
    )


def _render_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        progress = message.get("progress") or []
        if progress:
            with st.expander("Tool progress", expanded=False):
                for line in progress:
                    st.markdown(f"- {line}")
        st.markdown(message.get("content") or "")
        usage = message.get("usage")
        if usage:
            caption = TokenUsage.from_dict(usage).format_caption()
            if caption:
                st.caption(caption)


cached_tools = sorted(
    {
        key.split(":", 1)[0]
        for key in st.session_state.agent_tool_cache
        if not key.endswith(":__latest__")
    }
)
if cached_tools:
    st.caption(
        "Cached for this chat: "
        + ", ".join(f"`{name}`" for name in cached_tools)
    )

for message in st.session_state.agent_messages:
    _render_message(message)

if prompt := st.chat_input("Ask about Ceph test runs, failures, builds…"):
    st.session_state.agent_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    usage_out: dict = {}
    progress_lines: list[str] = []
    reply = ""
    with st.chat_message("assistant"):
        if not is_configured():
            reply = (
                "The agent can't answer yet — configure the `[llm]` section "
                "first."
            )
            st.markdown(reply)
        else:
            try:
                with st.status(
                    "Working on your question…",
                    expanded=True,
                ) as status:
                    def on_progress(message: str) -> None:
                        progress_lines.append(message)
                        status.write(message)
                        lowered = message.lower()
                        if lowered.startswith("finished"):
                            status.update(
                                label="Done",
                                state="complete",
                                expanded=False,
                            )
                        elif (
                            "fetching `" in lowered
                            or "reusing" in lowered
                            or "cache hit" in lowered
                            or "cached `" in lowered
                            or lowered.startswith("intent:")
                            or lowered.startswith("understanding")
                        ):
                            status.update(label=message, state="running")

                    reply = st.write_stream(
                        stream_chat(
                            st.session_state.agent_messages,
                            usage_out=usage_out,
                            on_progress=on_progress,
                            tool_cache=st.session_state.agent_tool_cache,
                        )
                    ) or ""

                if not reply:
                    reply = (
                        "The model returned an empty response. "
                        "Try again or check the local LLM server."
                    )
                    st.warning(reply)

                caption = TokenUsage.from_dict(usage_out).format_caption()
                if caption:
                    st.caption(caption)
            except LLMError as exc:
                reply = f"Sorry, I couldn't reach the LLM: {exc}"
                st.error(reply)

    entry: dict = {"role": "assistant", "content": reply}
    if progress_lines:
        entry["progress"] = progress_lines
    if usage_out:
        entry["usage"] = usage_out
    st.session_state.agent_messages.append(entry)
