"""
Reusable UI components for Streamlit interfaces.
"""
from typing import Any, Callable, Dict, List, Optional

import streamlit as st


def render_user_message(content: str, timestamp: str = "") -> None:
    """Render a user message using Streamlit's chat_message API."""
    with st.chat_message("user"):
        if timestamp:
            st.caption(timestamp)
        st.markdown(content)


def render_assistant_message(
    content: str,
    timestamp: str = "",
    response_time: float = 0,
    sources: Optional[List[Dict[str, Any]]] = None,
    on_like: Optional[Callable[[], None]] = None,
    on_dislike: Optional[Callable[[], None]] = None,
    key_prefix: str = "",
) -> None:
    """Render an assistant message with sources and feedback."""
    with st.chat_message("assistant"):
        if timestamp or response_time:
            meta_parts = []
            if timestamp:
                meta_parts.append(timestamp)
            if response_time:
                meta_parts.append(f"{response_time:.1f}s")
            st.caption(" | ".join(meta_parts))
        
        st.markdown(content)
        
        if sources:
            render_sources_collapsible(sources, key_prefix)
        
        if on_like or on_dislike:
            render_feedback_buttons(on_like, on_dislike, key_prefix)


def render_sources_collapsible(
    sources: List[Dict[str, Any]],
    key_prefix: str = "",
) -> None:
    """Render source citations in a collapsible expander."""
    if not sources:
        return
    
    with st.expander(f"Sources ({len(sources)})", expanded=False):
        for src in sources:
            render_single_source(src)


def render_single_source(src: Dict[str, Any]) -> None:
    """Render a single source citation."""
    idx = src.get("index", "")
    label = src.get("label") or f"Source {idx}"
    user = src.get("user")
    posted_at = src.get("posted_at")
    content = src.get("content", "")
    score = src.get("score", 0)
    thread_excerpt = src.get("thread_excerpt")
    message_link = src.get("message_permalink")
    thread_link = src.get("thread_permalink")
    source_link = src.get("source_link")
    
    header_parts = []
    if idx:
        header_parts.append(f"**[{idx}]**")
    header_parts.append(f"**{label}**")
    if score:
        header_parts.append(f"_(relevance: {score:.0%})_")
    
    st.markdown(" ".join(header_parts))
    
    meta_parts = []
    if user:
        meta_parts.append(user)
    if posted_at:
        meta_parts.append(posted_at)
    
    links = []
    if message_link:
        links.append(f"[Message]({message_link})")
    if thread_link and thread_link != message_link:
        links.append(f"[Thread]({thread_link})")
    if source_link and not message_link:
        links.append(f"[Source]({source_link})")
    
    if meta_parts or links:
        st.caption(" | ".join(meta_parts + links))
    
    if content:
        preview = content[:200] + "..." if len(content) > 200 else content
        st.markdown(f"> {preview}")
    
    if thread_excerpt:
        with st.expander("Thread context"):
            st.text(thread_excerpt)
    
    st.divider()


def render_sources_inline(sources: List[Dict[str, Any]]) -> None:
    """Render source citations inline (non-collapsible)."""
    if not sources:
        return
    
    st.markdown("**Sources:**")
    
    for src in sources:
        idx = src.get("index")
        label = src.get("label") or f"Source {idx}"
        user = src.get("user")
        posted_at = src.get("posted_at")
        message_link = src.get("message_permalink")
        source_link = src.get("source_link")
        
        pieces = []
        if idx:
            pieces.append(f"[{idx}]")
        
        if message_link:
            pieces.append(f"[{label}]({message_link})")
        elif source_link:
            pieces.append(f"[{label}]({source_link})")
        else:
            pieces.append(label)
        
        if user:
            pieces.append(user)
        if posted_at:
            pieces.append(posted_at)
        
        st.markdown(f"- {' | '.join(pieces)}")


def render_feedback_buttons(
    on_like: Optional[Callable[[], None]],
    on_dislike: Optional[Callable[[], None]],
    key_prefix: str = "",
) -> None:
    """Render feedback buttons in a horizontal layout."""
    col1, col2, _ = st.columns([1, 1, 6])
    
    with col1:
        if st.button("Like", key=f"{key_prefix}_like", help="Good response"):
            if on_like:
                on_like()
    
    with col2:
        if st.button("Dislike", key=f"{key_prefix}_dislike", help="Needs improvement"):
            if on_dislike:
                on_dislike()


def render_model_checkboxes(
    available_models: Dict[str, str],
    selected_key: str = "selected_models",
) -> Dict[str, str]:
    """Render model selection checkboxes."""
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Select All", use_container_width=True, key=f"{selected_key}_all"):
            st.session_state[selected_key] = dict(available_models)
            for model_id in available_models.values():
                st.session_state[f"model_{model_id}"] = True
    with col2:
        if st.button("Clear", use_container_width=True, key=f"{selected_key}_clear"):
            st.session_state[selected_key] = {}
            for model_id in available_models.values():
                st.session_state[f"model_{model_id}"] = False
    
    selected = {}
    
    if available_models:
        st.markdown("**Google Gemini**")
        for display_name, model_id in available_models.items():
            key = f"model_{model_id}"
            if key not in st.session_state:
                is_default = model_id == "gemini-2.5-flash"
                st.session_state[key] = is_default
            
            if st.checkbox(display_name, key=key):
                selected[display_name] = model_id
    
    st.session_state[selected_key] = selected
    
    if selected:
        st.success(f"{len(selected)} model(s) selected")
        if len(selected) > 1:
            st.info("Multiple models will be aggregated")
    else:
        st.warning("No models selected")
    
    return selected


def render_session_list(
    sessions: List[Dict[str, Any]],
    on_select: Callable[[str], None],
    key_prefix: str = "session",
) -> None:
    """Render a list of chat sessions."""
    if not sessions:
        st.info("No previous chats")
        return
    
    for session in sessions:
        session_id = session.get("session_id")
        first_query = session.get("first_query", "Untitled")[:30]
        timestamp = session.get("created_at", "")
        
        if st.button(
            f"{first_query}...",
            key=f"{key_prefix}_{session_id}",
            help=f"Created: {timestamp}",
            use_container_width=True,
        ):
            on_select(session_id)


def render_thinking_indicator(message: str = "Thinking...") -> None:
    """Render a thinking/loading indicator."""
    with st.chat_message("assistant"):
        with st.spinner(message):
            st.empty()


def render_error_message(error: str) -> None:
    """Render an error message in chat format."""
    with st.chat_message("assistant"):
        st.error(error)


def render_info_message(message: str) -> None:
    """Render an info message in chat format."""
    with st.chat_message("assistant"):
        st.info(message)
