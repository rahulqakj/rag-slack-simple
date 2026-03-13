"""
Analytics service for tracking queries and performance metrics.
"""
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.base import DatabaseConnection


logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for managing analytics and metrics."""
    
    def save_analytics(
        self,
        session_id: str,
        query: str,
        response_time: int,
        sources_used: Dict[str, Any],
        feedback_score: Optional[bool] = None,
    ) -> bool:
        """Save analytics data."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics (id, session_id, query, response_time_ms, sources_used, feedback_score)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (str(uuid.uuid4()), session_id, query, response_time, json.dumps(sources_used), feedback_score)
                )
            return True
        except Exception as e:
            logger.error("Error saving analytics: %s", e)
            return False
    
    def record_query(
        self,
        query: str,
        response: str,
        response_time: float,
        context_used: bool = False,
        models_used: Optional[str] = None,
        sources_used: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Record a query for analytics with enhanced tracking.
        
        Returns:
            Response ID for the recorded query
        """
        try:
            response_id = str(uuid.uuid4())
            response_time_ms = int(response_time * 1000)
            
            sources_payload = sources_used or {}
            if "models" not in sources_payload:
                sources_payload["models"] = models_used or []
            sources_payload.setdefault("context_used", context_used)
            sources_payload.setdefault("response_length", len(response) if response else 0)
            sources_payload.setdefault("timestamp", datetime.now().isoformat())
            
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO analytics (id, session_id, query, response_time_ms, sources_used, feedback_score, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (response_id, session_id, query, response_time_ms, json.dumps(sources_payload), None, datetime.now())
                )
            
            return response_id
            
        except Exception as e:
            logger.error("Error recording query analytics: %s", e)
            return str(uuid.uuid4())
    
    def update_feedback(self, response_id: str, feedback_score: bool) -> bool:
        """Update feedback score for a recorded query."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    "UPDATE analytics SET feedback_score = %s WHERE id = %s",
                    (feedback_score, response_id)
                )
            return True
        except Exception as e:
            logger.error("Error updating feedback: %s", e)
            return False
    
    def record_feedback(self, response_id: str, is_positive: bool) -> bool:
        """Record user feedback for a response."""
        return self.update_feedback(response_id, is_positive)
    
    def get_analytics_data(self, days: int = 30) -> Optional[Dict[str, Any]]:
        """Retrieve analytics data for dashboard."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                # Feedback statistics
                cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total_feedback,
                        SUM(CASE WHEN label = TRUE THEN 1 ELSE 0 END) as positive_feedback,
                        SUM(CASE WHEN label = FALSE THEN 1 ELSE 0 END) as negative_feedback
                    FROM feedback
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (days,)
                )
                feedback_stats = cursor.fetchone()
                
                # Daily query count
                cursor.execute(
                    """
                    SELECT DATE(created_at) as date, COUNT(*) as query_count
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(created_at)
                    ORDER BY date
                    """,
                    (days,)
                )
                daily_queries = cursor.fetchall()
                
                # Source usage
                cursor.execute(
                    """
                    SELECT sources_used, COUNT(*) as usage_count
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY sources_used
                    """,
                    (days,)
                )
                source_usage = cursor.fetchall()
                
                # Average response time
                cursor.execute(
                    """
                    SELECT AVG(response_time_ms) as avg_response_time
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (days,)
                )
                avg_response_time = cursor.fetchone()[0] or 0
                
                # Top queries
                cursor.execute(
                    """
                    SELECT query, COUNT(*) as query_count
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY query
                    ORDER BY query_count DESC
                    LIMIT 10
                    """,
                    (days,)
                )
                top_queries = cursor.fetchall()
                
                return {
                    "feedback_stats": feedback_stats,
                    "daily_queries": daily_queries,
                    "source_usage": source_usage,
                    "avg_response_time": avg_response_time,
                    "top_queries": top_queries,
                }
                
        except Exception as e:
            logger.error("Error retrieving analytics: %s", e)
            return None
    
    def get_session_analytics(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get analytics for a specific session."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total_queries,
                        AVG(response_time_ms) as avg_response_time,
                        COUNT(CASE WHEN feedback_score = TRUE THEN 1 END) as positive_feedback,
                        COUNT(CASE WHEN feedback_score = FALSE THEN 1 END) as negative_feedback
                    FROM analytics
                    WHERE session_id = %s
                    """,
                    (uuid.UUID(session_id),)
                )
                
                stats = cursor.fetchone()
                return {
                    "total_queries": stats[0],
                    "avg_response_time": stats[1] or 0,
                    "positive_feedback": stats[2],
                    "negative_feedback": stats[3],
                }
                
        except Exception as e:
            logger.error("Error retrieving session analytics: %s", e)
            return None
    
    def get_performance_metrics(self, days: int = 30) -> Optional[Dict[str, Any]]:
        """Get performance metrics."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                # Response time percentiles
                cursor.execute(
                    """
                    SELECT 
                        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY response_time_ms) as median,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY response_time_ms) as p95,
                        MIN(response_time_ms) as min_time,
                        MAX(response_time_ms) as max_time
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (days,)
                )
                response_time_stats = cursor.fetchone()
                
                # Success rate
                cursor.execute(
                    """
                    SELECT 
                        COUNT(*) as total_queries,
                        COUNT(CASE WHEN feedback_score IS NOT NULL THEN 1 END) as with_feedback,
                        COUNT(CASE WHEN feedback_score = TRUE THEN 1 END) as positive
                    FROM analytics
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """,
                    (days,)
                )
                success_stats = cursor.fetchone()
                
                return {
                    "response_time": {
                        "median": response_time_stats[0] or 0,
                        "p95": response_time_stats[1] or 0,
                        "min": response_time_stats[2] or 0,
                        "max": response_time_stats[3] or 0,
                    },
                    "success_rate": {
                        "total_queries": success_stats[0],
                        "queries_with_feedback": success_stats[1],
                        "positive_feedback": success_stats[2],
                        "success_rate": (success_stats[2] / success_stats[1] * 100) if success_stats[1] > 0 else 0,
                    },
                }
                
        except Exception as e:
            logger.error("Error retrieving performance metrics: %s", e)
            return None
    
    def get_sources_for_response(self, response_id: str) -> List[Dict[str, Any]]:
        """Get sources used for a specific response."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    "SELECT sources_used FROM analytics WHERE id = %s",
                    (response_id,)
                )
                result = cursor.fetchone()
                
                if result and result[0]:
                    sources_data = result[0]
                    if isinstance(sources_data, dict) and "kb_sources" in sources_data:
                        return sources_data["kb_sources"]
                
                return []
                
        except Exception:
            return []
    
    def get_sources_for_session_message(
        self,
        session_id: str,
        message_index: int,
    ) -> List[Dict[str, Any]]:
        """Get sources for a message in a session by index."""
        try:
            with DatabaseConnection.get_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, sources_used, created_at
                    FROM analytics
                    WHERE session_id = %s
                    ORDER BY created_at ASC
                    """,
                    (session_id,)
                )
                results = cursor.fetchall()
                
                if message_index < len(results):
                    sources_data = results[message_index][1]
                    if isinstance(sources_data, dict) and "kb_sources" in sources_data:
                        return sources_data["kb_sources"]
                
                return []
                
        except Exception:
            return []
