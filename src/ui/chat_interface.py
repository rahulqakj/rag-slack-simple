"""
Chat interface for the QA Assistant.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from src.core.chat_service import ChatService
from src.core.knowledge_service import KnowledgeService
from src.core.analytics_service import AnalyticsService
from src.core.llm_service import LLMService
from src.api.web_search_api import WebSearchAPI
from src.ui.components import (
    render_user_message,
    render_assistant_message,
    render_model_checkboxes,
    render_session_list,
)


SYSTEM_PROMPT_WITH_CONTEXT = """Kamu adalah QA Assistant yang membantu menjawab pertanyaan berdasarkan knowledge base.

INSTRUKSI:
1. Gunakan informasi dari Sources yang diberikan untuk menjawab pertanyaan
2. Jika Sources tidak mengandung informasi yang relevan, katakan "Saya tidak menemukan informasi spesifik tentang hal tersebut di knowledge base."
3. Selalu cantumkan referensi menggunakan format [Source X] saat mengutip informasi
4. Jawab dalam bahasa yang sama dengan pertanyaan (Indonesia/Inggris)
5. Berikan jawaban yang terstruktur dan mudah dipahami
6. Jika ada beberapa sumber yang relevan, sintesis informasinya

CONVERSATION HISTORY:
{history}

KNOWLEDGE SOURCES:
{sources}

USER QUESTION: {query}

Berikan jawaban yang informatif dan akurat berdasarkan sources di atas."""

SYSTEM_PROMPT_NO_CONTEXT = """Kamu adalah QA Assistant.

Saat ini tidak ada informasi relevan yang ditemukan di knowledge base untuk pertanyaan ini.

USER QUESTION: {query}

Jawab dengan: "Maaf, saya tidak menemukan informasi tentang hal tersebut di knowledge base yang tersedia. Silakan upload dokumen terkait atau coba pertanyaan yang berbeda."
"""


class ChatInterface:
    """Main chat interface for the QA Assistant."""
    
    DEFAULT_HISTORY_LIMIT = 12
    DEFAULT_MODEL = ("Gemini 2.5 Flash", "gemini-2.5-flash")
    
    def __init__(self):
        self.chat_service = ChatService()
        self.knowledge_service = KnowledgeService()
        self.analytics_service = AnalyticsService()
        self.llm_service = LLMService()
        self.web_search_api = WebSearchAPI()
    
    def render(self) -> None:
        """Render the chat interface."""
        st.title("QA Assistant Chat")
        
        self._initialize_session_state()
        self._render_sidebar()
        self._render_messages()
        
        query = st.chat_input("Tanyakan sesuatu...")
        
        if query:
            self._handle_query(query)
            st.rerun()
    
    def _initialize_session_state(self) -> None:
        """Initialize session state with proper defaults."""
        if st.session_state.get("new_chat_clicked"):
            st.session_state.pop("new_chat_clicked", None)
            self._ensure_defaults()
            return
        
        session_id_from_url = st.query_params.get("session_id")
        
        need_to_load = (
            "session_id" not in st.session_state
            or (session_id_from_url and st.session_state.get("session_id") != session_id_from_url)
            or not st.session_state.get("chat_messages")
        )
        
        if need_to_load:
            if session_id_from_url:
                self._load_session(session_id_from_url)
            
            if "session_id" not in st.session_state:
                self._try_load_recent_session()
            
            if "session_id" not in st.session_state:
                self._start_new_session()
        
        if st.session_state.get("session_id"):
            if st.query_params.get("session_id") != st.session_state.session_id:
                st.query_params["session_id"] = st.session_state.session_id
        
        self._ensure_defaults()
    
    def _ensure_defaults(self) -> None:
        """Ensure required session state defaults exist."""
        if "selected_models" not in st.session_state:
            name, model_id = self.DEFAULT_MODEL
            st.session_state.selected_models = {name: model_id}
            st.session_state[f"model_{model_id}"] = True
        
        if "chat_history_context_limit" not in st.session_state:
            st.session_state.chat_history_context_limit = self.DEFAULT_HISTORY_LIMIT
        
        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = []
    
    def _start_new_session(self) -> None:
        """Start a fresh chat session."""
        new_id = str(uuid.uuid4())
        st.session_state.session_id = new_id
        st.session_state.chat_messages = []
        st.query_params["session_id"] = new_id
    
    def _load_session(self, session_id: str) -> None:
        """Load a specific session by ID."""
        messages = self.chat_service.get_session_messages(session_id)
        
        if not messages:
            return
        
        st.session_state.session_id = session_id
        st.session_state.chat_messages = []
        
        assistant_idx = 0
        for msg in messages:
            msg_data = {
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
                "timestamp": msg.get("created_at", ""),
                "models_used": msg.get("models_used", ""),
                "response_id": msg.get("id"),
                "response_time": msg.get("response_time", 0),
                "saved": True,
            }
            
            if msg.get("role") == "assistant":
                try:
                    sources = self.analytics_service.get_sources_for_session_message(session_id, assistant_idx)
                    if sources:
                        msg_data["sources"] = sources
                except Exception:
                    pass
                assistant_idx += 1
            
            st.session_state.chat_messages.append(msg_data)
    
    def _try_load_recent_session(self) -> None:
        """Try to load the most recent session."""
        try:
            sessions = self.chat_service.get_recent_sessions(limit=1)
            if sessions:
                self._load_session(sessions[0].get("session_id"))
        except Exception:
            pass
    
    def _render_sidebar(self) -> None:
        """Render sidebar controls."""
        with st.sidebar:
            st.subheader("AI Models")
            render_model_checkboxes(self.llm_service.get_available_models())
            
            st.divider()
            
            st.subheader("Chat Controls")
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("New", use_container_width=True):
                    self._on_new_chat()
            
            with col2:
                if st.button("Save", use_container_width=True):
                    self._save_messages()
                    st.success("Saved!")
            
            msg_count = len(st.session_state.get("chat_messages", []))
            if msg_count > 0:
                st.caption(f"{msg_count} messages in this chat")
            
            st.divider()
            
            st.subheader("RAG Settings")
            st.session_state.use_kb = st.checkbox("Knowledge Base", value=True)
            st.session_state.use_web = st.checkbox("Web Search", value=False)
            st.session_state.use_history = st.checkbox("Similar Chats", value=True)
            st.session_state.chat_history_context_limit = st.slider(
                "History turns",
                min_value=2,
                max_value=20,
                value=st.session_state.chat_history_context_limit,
                step=2,
            )
            
            st.divider()
            
            st.subheader("Recent Chats")
            try:
                sessions = self.chat_service.get_recent_sessions(limit=8)
                render_session_list(sessions, self._on_session_select, "load")
            except Exception as e:
                st.error(f"Error: {e}")
    
    def _on_new_chat(self) -> None:
        """Handle new chat button click."""
        new_id = str(uuid.uuid4())
        selected = st.session_state.get("selected_models", {})
        st.session_state.clear()
        st.session_state.chat_messages = []
        st.session_state.session_id = new_id
        st.session_state.selected_models = selected
        st.session_state.new_chat_clicked = True
        st.query_params.clear()
        st.query_params["session_id"] = new_id
        st.rerun()
    
    def _on_session_select(self, session_id: str) -> None:
        """Handle session selection from sidebar."""
        self._load_session(session_id)
        st.query_params["session_id"] = session_id
        st.rerun()
    
    def _handle_query(self, query: str) -> None:
        """Process a user query and generate response."""
        if not st.session_state.selected_models:
            name, model_id = self.DEFAULT_MODEL
            st.session_state.selected_models = {name: model_id}
            st.session_state[f"model_{model_id}"] = True
        
        timestamp = datetime.now().strftime("%H:%M")
        st.session_state.chat_messages.append({
            "role": "user",
            "content": query,
            "timestamp": timestamp,
        })
        
        response_data = self._process_query(query)
        
        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": response_data["response"],
            "timestamp": datetime.now().strftime("%H:%M"),
            "models_used": response_data.get("models_used", ""),
            "response_time": response_data.get("response_time", 0),
            "response_id": response_data.get("response_id"),
            "sources": response_data.get("sources"),
        })
        
        self._save_messages()
    
    def _process_query(self, query: str) -> Dict[str, Any]:
        """Process user query with improved RAG pipeline."""
        start_time = datetime.now()
        
        use_kb = st.session_state.get("use_kb", True)
        use_web = st.session_state.get("use_web", False)
        use_history = st.session_state.get("use_history", True)
        
        try:
            history_context = ""
            sources_context = ""
            kb_sources = []
            web_sources = []
            
            history_limit = st.session_state.get("chat_history_context_limit", self.DEFAULT_HISTORY_LIMIT)
            history = self.chat_service.retrieve_chat_memory(st.session_state.session_id, history_limit)
            if history:
                history_context = "\n".join(history[-10:])
            
            if use_history:
                try:
                    similar = self.chat_service.search_similar_conversations(
                        query,
                        current_session_id=st.session_state.session_id,
                        limit=3,
                    )
                    if similar:
                        similar_lines = []
                        for conv in similar:
                            if conv.get("combined_score", 0) > 0.3:
                                similar_lines.append(
                                    f"Q: {conv.get('user_message', '')}\n"
                                    f"A: {conv.get('assistant_message', '')[:200]}..."
                                )
                        if similar_lines:
                            history_context += "\n\nRelevant past Q&A:\n" + "\n\n".join(similar_lines)
                except Exception:
                    pass
            
            if use_kb:
                try:
                    kb_sources, sources_context = self.knowledge_service.get_context_for_query(
                        query,
                        max_results=8,
                        max_chars=10000,
                    )
                except Exception:
                    pass
            
            if use_web:
                try:
                    web_results = self.web_search_api.search_web(query)
                    if web_results:
                        web_lines = []
                        for idx, result in enumerate(web_results, len(kb_sources) + 1):
                            title = result.get("title", "Web Result")
                            content = (result.get("content", ""))[:300]
                            url = result.get("url", "")
                            web_lines.append(f"[Source {idx}] {title}\n{content}\nURL: {url}")
                            web_sources.append({
                                "index": idx,
                                "label": title,
                                "content": content,
                                "source_link": url,
                            })
                        if web_lines:
                            sources_context += "\n\n---\n\nWeb Results:\n" + "\n\n".join(web_lines)
                except Exception:
                    pass
            
            if sources_context or history_context:
                prompt = SYSTEM_PROMPT_WITH_CONTEXT.format(
                    history=history_context or "No previous conversation.",
                    sources=sources_context or "No sources found.",
                    query=query,
                )
            else:
                prompt = SYSTEM_PROMPT_NO_CONTEXT.format(query=query)
            
            selected_models = st.session_state.get("selected_models", {})
            first_model = list(selected_models.items())[0]
            model_name, model_id = first_model
            response = self.llm_service.generate_single_response(model_id, query, prompt)
            models_used = model_name
            
            response_time = (datetime.now() - start_time).total_seconds()
            
            all_sources = kb_sources + web_sources
            sources_payload = {
                "models": models_used,
                "context_used": bool(sources_context),
                "kb_sources": kb_sources,
                "web_sources": web_sources,
            }
            
            response_id = self.analytics_service.record_query(
                query=query,
                response=response,
                response_time=response_time,
                context_used=bool(sources_context),
                models_used=models_used,
                sources_used=sources_payload,
                session_id=st.session_state.session_id,
            )
            
            return {
                "response": response,
                "response_time": response_time,
                "models_used": models_used,
                "response_id": response_id,
                "sources": all_sources,
            }
            
        except Exception as e:
            return {
                "response": f"Terjadi error saat memproses pertanyaan: {str(e)}",
                "response_time": 0,
                "models_used": "Error",
                "response_id": None,
                "sources": [],
            }
    
    def _render_messages(self) -> None:
        """Render all chat messages using modern Streamlit chat API."""
        for i, message in enumerate(st.session_state.get("chat_messages", [])):
            if message["role"] == "user":
                render_user_message(message["content"], message.get("timestamp", ""))
            else:
                response_id = message.get("response_id")
                
                def make_feedback_handler(rid: str, positive: bool):
                    def handler():
                        if rid:
                            self.analytics_service.record_feedback(rid, positive)
                            st.toast("Terima kasih!" if positive else "Terima kasih atas feedback!")
                    return handler
                
                render_assistant_message(
                    content=message["content"],
                    timestamp=message.get("timestamp", ""),
                    response_time=message.get("response_time", 0),
                    sources=message.get("sources"),
                    on_like=make_feedback_handler(response_id, True) if response_id else None,
                    on_dislike=make_feedback_handler(response_id, False) if response_id else None,
                    key_prefix=f"msg_{i}",
                )
    
    def _save_messages(self) -> None:
        """Save unsaved messages to database."""
        try:
            for message in st.session_state.get("chat_messages", []):
                if not message.get("saved", False):
                    self.chat_service.save_message(
                        session_id=st.session_state.session_id,
                        role=message["role"],
                        content=message["content"],
                        models_used=message.get("models_used", ""),
                        response_time=message.get("response_time", 0),
                    )
                    message["saved"] = True
        except Exception:
            pass
