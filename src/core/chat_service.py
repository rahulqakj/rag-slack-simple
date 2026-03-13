"""
Chat history and feedback service.
"""
import logging
import uuid
from typing import Any, Dict, List, Optional

from src.core.base import DatabaseConnection, EmbeddingVector
from src.core.embedding_service import EmbeddingService


logger = logging.getLogger(__name__)


class ChatService:
    """Service for managing chat history and feedback."""
    
    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self.embedding_service = embedding_service or EmbeddingService()
    
    def save_chat_history(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        embedding: Optional[List[float]] = None,
    ) -> Optional[str]:
        """
        Save a chat interaction to the database.
        
        Returns:
            Chat ID if successful, None otherwise
        """
        chat_id = str(uuid.uuid4())
        
        try:
            embedding_str = None
            if embedding:
                embedding_str = EmbeddingVector(values=embedding).to_pg_literal()
            
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_history (id, session_id, user_message, assistant_message, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (chat_id, session_id, user_message, assistant_message, embedding_str)
                )
            
            return chat_id
            
        except Exception as e:
            logger.error("Error saving chat history: %s", e)
            return None
    
    def retrieve_chat_memory(self, session_id: str, limit: int = 5) -> List[str]:
        """
        Retrieve recent chat history for a session as formatted lines.
        
        Returns:
            List of formatted message strings
        """
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT user_message, assistant_message FROM chat_history
                    WHERE session_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (session_id, limit)
                )
                rows = cursor.fetchall()
            
            lines = []
            for row in reversed(rows):
                user_msg = row[0] or ""
                assistant_msg = row[1] or ""
                lines.append(f"User: {user_msg}")
                lines.append(f"Assistant: {assistant_msg}")
            
            return lines
            
        except Exception as e:
            logger.error("Error retrieving chat memory: %s", e)
            return []
    
    def search_similar_conversations(
        self,
        query: str,
        current_session_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search for similar conversations using hybrid search.
        
        Args:
            query: Search query
            current_session_id: Optional session ID to exclude
            limit: Maximum results
            
        Returns:
            List of similar conversation records
        """
        try:
            query_embedding = self.embedding_service.embed_text(query)
            if not query_embedding:
                return []
            
            vector = EmbeddingVector(values=query_embedding)
            keywords = query.lower().strip()
            
            with DatabaseConnection.get_cursor() as cursor:
                if current_session_id:
                    cursor.execute(
                        """
                        WITH keyword_results AS (
                            SELECT 
                                session_id, user_message, assistant_message, created_at,
                                -- Use pg_textsearch BM25 operator (returns negative, normalize to 0-1)
                                GREATEST(0, LEAST(1, -(user_message <@> to_bm25query(%s, 'idx_chat_history_bm25')) / 10)) as text_score
                            FROM chat_history
                            WHERE session_id != %s 
                              AND (user_message ILIKE %s OR assistant_message ILIKE %s)
                        ),
                        semantic_results AS (
                            SELECT 
                                session_id, user_message, assistant_message, created_at,
                                1 - (embedding <-> %s::vector) as similarity_score
                            FROM chat_history
                            WHERE session_id != %s AND embedding IS NOT NULL
                            ORDER BY embedding <-> %s::vector
                            LIMIT %s
                        )
                        SELECT DISTINCT 
                            COALESCE(k.session_id, s.session_id),
                            COALESCE(k.user_message, s.user_message),
                            COALESCE(k.assistant_message, s.assistant_message),
                            COALESCE(k.created_at, s.created_at),
                            COALESCE(k.text_score, 0) * 0.4 + COALESCE(s.similarity_score, 0) * 0.6
                        FROM keyword_results k
                        FULL OUTER JOIN semantic_results s 
                            ON k.session_id = s.session_id AND k.created_at = s.created_at
                        ORDER BY 5 DESC
                        LIMIT %s
                        """,
                        (
                            keywords, current_session_id, f"%{keywords}%", f"%{keywords}%",
                            vector.to_pg_literal(), current_session_id, vector.to_pg_literal(),
                            limit * 2, limit
                        )
                    )
                else:
                    cursor.execute(
                        """
                        WITH keyword_results AS (
                            SELECT 
                                session_id, user_message, assistant_message, created_at,
                                -- Use pg_textsearch BM25 operator (returns negative, normalize to 0-1)
                                GREATEST(0, LEAST(1, -(user_message <@> to_bm25query(%s, 'idx_chat_history_bm25')) / 10)) as text_score
                            FROM chat_history
                            WHERE (user_message ILIKE %s OR assistant_message ILIKE %s)
                        ),
                        semantic_results AS (
                            SELECT 
                                session_id, user_message, assistant_message, created_at,
                                1 - (embedding <-> %s::vector) as similarity_score
                            FROM chat_history
                            WHERE embedding IS NOT NULL
                            ORDER BY embedding <-> %s::vector
                            LIMIT %s
                        )
                        SELECT DISTINCT 
                            COALESCE(k.session_id, s.session_id),
                            COALESCE(k.user_message, s.user_message),
                            COALESCE(k.assistant_message, s.assistant_message),
                            COALESCE(k.created_at, s.created_at),
                            COALESCE(k.text_score, 0) * 0.4 + COALESCE(s.similarity_score, 0) * 0.6
                        FROM keyword_results k
                        FULL OUTER JOIN semantic_results s 
                            ON k.session_id = s.session_id AND k.created_at = s.created_at
                        ORDER BY 5 DESC
                        LIMIT %s
                        """,
                        (
                            keywords, f"%{keywords}%", f"%{keywords}%",
                            vector.to_pg_literal(), vector.to_pg_literal(),
                            limit * 2, limit
                        )
                    )
                
                results = []
                for row in cursor.fetchall():
                    results.append({
                        "session_id": row[0],
                        "user_message": row[1],
                        "assistant_message": row[2],
                        "created_at": row[3],
                        "combined_score": row[4],
                    })
                
                return results
                
        except Exception as e:
            logger.error("Error searching similar conversations: %s", e)
            return []
    
    def save_feedback(
        self,
        chat_id: str,
        query: str,
        answer: str,
        is_good: bool,
        notes: str = "",
    ) -> bool:
        """Save user feedback for a chat interaction."""
        if not chat_id:
            logger.error("Cannot save feedback: Invalid chat session")
            return False
        
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO feedback (id, chat_id, query, answer, label, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), uuid.UUID(chat_id), query, answer, is_good, notes)
                )
            return True
        except Exception as e:
            logger.error("Error saving feedback: %s", e)
            return False
    
    def retrieve_feedback(self, embedding: List[float]) -> str:
        """Retrieve negative feedback for similar queries."""
        try:
            vector = EmbeddingVector(values=embedding)
            
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT ch.user_message, f.answer, f.notes
                    FROM feedback f
                    JOIN chat_history ch ON f.chat_id = ch.id
                    WHERE f.label = FALSE
                    ORDER BY ch.embedding <-> %s::vector
                    LIMIT 3
                    """,
                    (vector.to_pg_literal(),)
                )
                
                feedback_notes = []
                for row in cursor.fetchall():
                    user_q = row[0] or ""
                    ans = (row[1] or "")[:100]
                    note = f"⚠️ Previous similar question: '{user_q}'. The answer '{ans}...' was marked as not good."
                    if row[2]:
                        note += f" Additional feedback: {row[2]}"
                    feedback_notes.append(note)
                
                return "\n".join(feedback_notes)
                
        except Exception as e:
            logger.error("Error retrieving feedback: %s", e)
            return ""
    
    def get_chat_stats(self, session_id: Optional[str] = None) -> Dict[str, int]:
        """Get statistics about chat interactions."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                if session_id:
                    cursor.execute(
                        "SELECT COUNT(*) FROM chat_history WHERE session_id = %s",
                        (session_id,)
                    )
                    total_messages = cursor.fetchone()[0]
                    
                    cursor.execute(
                        """
                        SELECT COUNT(*) FROM feedback f
                        JOIN chat_history ch ON f.chat_id = ch.id
                        WHERE ch.session_id = %s
                        """,
                        (session_id,)
                    )
                    total_feedback = cursor.fetchone()[0]
                else:
                    cursor.execute("SELECT COUNT(*) FROM chat_history")
                    total_messages = cursor.fetchone()[0]
                    
                    cursor.execute("SELECT COUNT(*) FROM feedback")
                    total_feedback = cursor.fetchone()[0]
                
                return {
                    "total_messages": total_messages,
                    "total_feedback": total_feedback,
                }
        except Exception as e:
            logger.error("Error getting chat stats: %s", e)
            return {"total_messages": 0, "total_feedback": 0}
    
    def get_recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get list of recent chat sessions."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT session_id, 
                           MIN(user_message) as first_query,
                           MIN(created_at) as created_at
                    FROM chat_history 
                    GROUP BY session_id 
                    ORDER BY MIN(created_at) DESC 
                    LIMIT %s
                    """,
                    (limit,)
                )
                
                sessions = []
                for row in cursor.fetchall():
                    sessions.append({
                        "session_id": row[0],
                        "first_query": row[1],
                        "created_at": row[2].strftime("%Y-%m-%d %H:%M") if row[2] else "",
                    })
                
                return sessions
                
        except Exception as e:
            logger.error("Error retrieving recent sessions: %s", e)
            return []
    
    def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a specific session."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_message, assistant_message, created_at
                    FROM chat_history
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,)
                )
                
                messages = []
                for row in cursor.fetchall():
                    chat_id = row[0]
                    created_at = row[3].strftime("%H:%M") if row[3] else ""
                    
                    messages.append({
                        "role": "user",
                        "content": row[1],
                        "created_at": created_at,
                        "id": None,
                    })
                    messages.append({
                        "role": "assistant",
                        "content": row[2],
                        "created_at": created_at,
                        "models_used": "Historical",
                        "response_time": 0,
                        "id": str(chat_id),
                    })
                
                return messages
                
        except Exception as e:
            logger.error("Error retrieving session messages: %s", e)
            return []
    
    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        models_used: str = "",
        response_time: float = 0,
    ) -> Optional[str]:
        """Save a single message to chat history with embedding."""
        chat_id = str(uuid.uuid4())
        
        try:
            with DatabaseConnection.get_connection() as conn:
                with conn.cursor() as cursor:
                    if role == "user":
                        embedding = self.embedding_service.embed_text(content)
                        embedding_str = None
                        if embedding:
                            embedding_str = EmbeddingVector(values=embedding).to_pg_literal()
                        
                        cursor.execute(
                            """
                            INSERT INTO chat_history (id, session_id, user_message, assistant_message, embedding)
                            VALUES (%s, %s, %s, NULL, %s)
                            """,
                            (chat_id, session_id, content, embedding_str)
                        )
                        return chat_id
                    else:
                        # Update the last user message row with assistant response
                        cursor.execute(
                            """
                            UPDATE chat_history 
                            SET assistant_message = %s, created_at = CURRENT_TIMESTAMP
                            WHERE id = (
                                SELECT id FROM chat_history 
                                WHERE session_id = %s AND assistant_message IS NULL 
                                ORDER BY created_at DESC LIMIT 1
                            )
                            """,
                            (content, session_id)
                        )
                        
                        if cursor.rowcount == 0:
                            cursor.execute(
                                """
                                INSERT INTO chat_history (id, session_id, user_message, assistant_message)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (chat_id, session_id, "Previous conversation", content)
                            )
                        
                        return chat_id
                        
        except Exception as e:
            logger.error("Error saving message: %s", e)
            return None
