"""
Knowledge base service for document storage and retrieval.
"""
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from src.core.base import DatabaseConnection, EmbeddingVector
from src.core.embedding_service import EmbeddingService


logger = logging.getLogger(__name__)

MIN_RELEVANCE_SCORE = 0.25
MAX_CONTEXT_CHARS = 12000


class KnowledgeService:
    """Service for managing the knowledge base with optimized RAG retrieval."""
    
    def __init__(self, embedding_service: Optional[EmbeddingService] = None):
        self.embedding_service = embedding_service or EmbeddingService()
    
    def retrieve_similar_docs(
        self,
        embedding: List[float],
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve documents similar to the given embedding.
        
        Args:
            embedding: Query embedding vector
            top_k: Maximum number of results
            min_score: Minimum similarity score (0-1)
            
        Returns:
            List of document dicts with id, content, metadata, and score
        """
        try:
            vector = EmbeddingVector(values=embedding)
            
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        id, 
                        content, 
                        metadata,
                        1 - (embedding <-> %s::vector) as similarity
                    FROM knowledge_chunks 
                    ORDER BY embedding <-> %s::vector 
                    LIMIT %s
                    """,
                    (vector.to_pg_literal(), vector.to_pg_literal(), top_k * 2)
                )
                
                docs = []
                for row in cursor.fetchall():
                    score = row[3] or 0
                    if score >= min_score:
                        metadata = self._parse_metadata(row[2])
                        docs.append({
                            "id": row[0],
                            "content": row[1],
                            "metadata": metadata,
                            "score": score,
                        })
                
                return docs[:top_k]
                
        except Exception as e:
            logger.error("Error retrieving documents: %s", e)
            return []
    
    def search_knowledge_base(
        self,
        query: str,
        limit: int = 10,
        min_score: float = MIN_RELEVANCE_SCORE,
    ) -> List[Dict[str, Any]]:
        """
        Search knowledge base using hybrid search (keyword + semantic).
        
        Args:
            query: Search query text
            limit: Maximum number of results
            min_score: Minimum relevance score (default MIN_RELEVANCE_SCORE)
            
        Returns:
            List of relevant documents with scores
        """
        try:
            processed_query = self._preprocess_query(query)
            
            query_embedding = self.embedding_service.embed_text(processed_query)
            if not query_embedding:
                logger.warning("Failed to generate embeddings for search query")
                return []
            
            vector = EmbeddingVector(values=query_embedding)
            keywords = self._extract_keywords(query)
            
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    WITH semantic_scores AS (
                        SELECT 
                            id,
                            content,
                            metadata,
                            GREATEST(0, 1 - (embedding <-> %s::vector) / 2) as semantic_score
                        FROM knowledge_chunks
                        WHERE embedding IS NOT NULL
                    ),
                    keyword_scores AS (
                        SELECT 
                            id,
                            -- Use pg_textsearch BM25 operator (returns negative, so negate it)
                            -- Normalize to 0-1 range with GREATEST/LEAST
                            GREATEST(0, LEAST(1, -(content <@> to_bm25query(%s, 'idx_knowledge_chunks_bm25')) / 10)) +
                            CASE WHEN content ILIKE %s THEN 0.3 ELSE 0 END as text_score
                        FROM knowledge_chunks
                    )
                    SELECT DISTINCT ON (s.id)
                        s.id,
                        s.content,
                        s.metadata,
                        (COALESCE(s.semantic_score, 0) * 0.65 + COALESCE(k.text_score, 0) * 0.35) as combined_score,
                        s.semantic_score,
                        COALESCE(k.text_score, 0) as text_score
                    FROM semantic_scores s
                    LEFT JOIN keyword_scores k ON s.id = k.id
                    WHERE s.semantic_score >= %s OR k.text_score > 0.1
                    ORDER BY s.id, combined_score DESC
                    """,
                    (
                        vector.to_pg_literal(),
                        keywords,
                        f"%{keywords}%",
                        min_score * 0.5,
                    )
                )
                
                raw_results = cursor.fetchall()
            
            docs = []
            seen_content = set()
            raw_results = sorted(raw_results, key=lambda x: x[3] or 0, reverse=True)
            
            for row in raw_results:
                combined_score = row[3] or 0
                
                if combined_score < min_score:
                    continue
                
                content = row[1] or ""
                content_key = content[:200].lower().strip()
                if content_key in seen_content:
                    continue
                seen_content.add(content_key)
                
                metadata = self._parse_metadata(row[2])
                docs.append({
                    "id": row[0],
                    "content": content,
                    "metadata": metadata,
                    "score": combined_score,
                    "semantic_score": row[4],
                    "text_score": row[5],
                })
                
                if len(docs) >= limit:
                    break
            
            return docs
                
        except Exception as e:
            logger.error("Error searching knowledge base: %s", e)
            try:
                query_embedding = self.embedding_service.embed_text(query)
                if query_embedding:
                    return self.retrieve_similar_docs(query_embedding, limit, min_score)
            except Exception as fallback_error:
                logger.error("Fallback search also failed: %s", fallback_error)
            return []
    
    def search_similar_content(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Alias for search_knowledge_base."""
        return self.search_knowledge_base(query, limit)
    
    def get_context_for_query(
        self,
        query: str,
        max_results: int = 10,
        max_chars: int = MAX_CONTEXT_CHARS,
    ) -> tuple[List[Dict[str, Any]], str]:
        """
        Get formatted context for a query, optimized for LLM consumption.
        
        Returns:
            Tuple of (source_list, formatted_context_string)
        """
        results = self.search_knowledge_base(query, limit=max_results)
        
        if not results:
            return [], ""
        
        formatted_parts = []
        sources = []
        total_chars = 0
        
        for idx, result in enumerate(results, 1):
            content = result.get("content", "").strip()
            metadata = result.get("metadata", {})
            score = result.get("score", 0)
            
            if total_chars + len(content) > max_chars:
                remaining = max_chars - total_chars - 100
                if remaining > 200:
                    content = content[:remaining] + "..."
                else:
                    break
            
            source_label = metadata.get("channel_name") or metadata.get("source") or "Document"
            user = metadata.get("user_display_name") or metadata.get("user_id") or ""
            posted_at = metadata.get("posted_at") or ""
            
            formatted_parts.append(
                f"[Source {idx}] {source_label} (relevance: {score:.2f})\n"
                f"{f'Author: {user} | ' if user else ''}"
                f"{f'Date: {posted_at} | ' if posted_at else ''}\n"
                f"Content: {content}"
            )
            
            sources.append({
                "index": idx,
                "label": source_label,
                "content": content[:300],
                "user": user,
                "posted_at": posted_at,
                "score": score,
                "message_permalink": metadata.get("message_permalink"),
                "thread_permalink": metadata.get("thread_permalink"),
                "thread_excerpt": metadata.get("thread_root_excerpt"),
                "source_link": metadata.get("source_link"),
            })
            
            total_chars += len(content)
        
        context_text = "\n\n---\n\n".join(formatted_parts)
        
        return sources, context_text
    
    def add_to_knowledge_base(
        self,
        text: str,
        filename: str,
        source_link: Optional[str] = None,
    ) -> int:
        """
        Add processed text to knowledge base.
        
        Args:
            text: The text content to add
            filename: Name of the source file
            source_link: Optional URL source of the document
            
        Returns:
            Number of chunks added
        """
        if not text or not text.strip():
            logger.error("Empty text for file: %s", filename)
            return 0
        
        from src.utils.text_chunker import SemanticChunker
        chunker = SemanticChunker(chunk_size=800, chunk_overlap=150)
        chunks = chunker.split(text)
        
        logger.info("File: %s, Text length: %d, Chunks: %d", filename, len(text), len(chunks))
        
        if not chunks:
            logger.error("No chunks generated for file: %s", filename)
            return 0
        
        chunks_added = 0
        
        try:
            with DatabaseConnection.get_connection() as conn:
                with conn.cursor() as cursor:
                    for chunk in chunks:
                        try:
                            content = chunk.content
                            embedding = self.embedding_service.embed_text(content)
                            
                            if embedding:
                                metadata = {
                                    "source": filename,
                                    "chunk_index": chunk.index,
                                    "char_start": chunk.start_char,
                                    "char_end": chunk.end_char,
                                }
                                if source_link:
                                    metadata["source_link"] = source_link
                                
                                vector = EmbeddingVector(values=embedding)
                                cursor.execute(
                                    """
                                    INSERT INTO knowledge_chunks (id, content, embedding, metadata) 
                                    VALUES (%s, %s, %s, %s)
                                    """,
                                    (str(uuid.uuid4()), content, vector.to_pg_literal(), json.dumps(metadata))
                                )
                                chunks_added += 1
                            else:
                                logger.warning(
                                    "Failed to generate embedding for chunk %d of %s",
                                    chunk.index, filename
                                )
                        except Exception as chunk_error:
                            logger.error(
                                "Failed to process chunk %d of %s: %s",
                                chunk.index, filename, chunk_error
                            )
                            continue
                
                conn.commit()
            
            logger.info("File: %s, Added %d/%d chunks", filename, chunks_added, len(chunks))
            return chunks_added
            
        except Exception as e:
            logger.error("Failed to add %s to knowledge base: %s", filename, e)
            return 0
    
    def get_knowledge_stats(self) -> Dict[str, Any]:
        """Get statistics about the knowledge base."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM knowledge_chunks")
                total_chunks = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(DISTINCT metadata->>'source') FROM knowledge_chunks")
                total_files = cursor.fetchone()[0]
                
                cursor.execute("""
                    SELECT metadata->>'source' as source, COUNT(*) as count 
                    FROM knowledge_chunks 
                    GROUP BY metadata->>'source' 
                    ORDER BY count DESC 
                    LIMIT 10
                """)
                top_sources = cursor.fetchall()
                
                return {
                    "total_chunks": total_chunks,
                    "total_files": total_files,
                    "top_sources": top_sources,
                }
        except Exception as e:
            logger.error("Error getting knowledge stats: %s", e)
            return {"total_chunks": 0, "total_files": 0, "top_sources": []}
    
    def delete_knowledge_chunk(self, chunk_id: str) -> bool:
        """Delete a specific knowledge chunk."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute("DELETE FROM knowledge_chunks WHERE id = %s", (chunk_id,))
            return True
        except Exception as e:
            logger.error("Error deleting knowledge chunk: %s", e)
            return False
    
    def _preprocess_query(self, query: str) -> str:
        """Preprocess query for better embedding and matching."""
        query = " ".join(query.split())
        
        expansions = {
            r"\bAPI\b": "API application programming interface",
            r"\bUI\b": "UI user interface",
            r"\bUX\b": "UX user experience",
            r"\bDB\b": "DB database",
            r"\bQA\b": "QA quality assurance",
        }
        
        for pattern, replacement in expansions.items():
            if re.search(pattern, query, re.IGNORECASE):
                query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
        
        return query
    
    def _extract_keywords(self, query: str) -> str:
        """Extract keywords from query for text search."""
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "to", "of", "in", "for", "on", "with", "at", "by",
            "from", "as", "into", "through", "during", "before", "after",
            "above", "below", "between", "under", "again", "further",
            "then", "once", "here", "there", "when", "where", "why",
            "how", "all", "each", "few", "more", "most", "other", "some",
            "such", "no", "nor", "not", "only", "own", "same", "so",
            "than", "too", "very", "just", "also", "now", "what", "which",
            "who", "this", "that", "these", "those", "i", "me", "my",
            "apa", "bagaimana", "dimana", "siapa", "kapan", "mengapa",
            "yang", "dan", "atau", "untuk", "dari", "ke", "di", "dengan",
        }
        
        words = re.findall(r"\b\w+\b", query.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2]
        
        return " ".join(keywords) if keywords else query.lower()
    
    def _parse_metadata(self, metadata: Any) -> Dict:
        """Parse metadata from database row."""
        if metadata is None:
            return {}
        if isinstance(metadata, dict):
            return metadata
        if isinstance(metadata, str):
            try:
                return json.loads(metadata)
            except json.JSONDecodeError:
                return {"raw": metadata}
        return {}
