"""
Async job queue service for background processing.
"""
import logging
from typing import Any, Dict, List, Optional

from psycopg2.extras import Json

from src.core.base import DatabaseConnection


logger = logging.getLogger(__name__)


class JobService:
    """Service for enqueueing and tracking asynchronous jobs."""
    
    @staticmethod
    def enqueue_slack_job(
        job_id: str,
        *,
        zip_path: str,
        channel_id: str,
        channel_name: str,
        workspace_domain: str,
        original_filename: str,
        requested_by: Optional[str] = None,
    ) -> str:
        """Register a Slack ingestion job in the async queue."""
        payload = {
            "zip_path": zip_path,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "workspace_domain": workspace_domain,
            "original_filename": original_filename,
            "requested_by": requested_by,
        }
        
        with DatabaseConnection.get_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO async_jobs (id, job_type, payload, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, NOW(), NOW())
                """,
                (job_id, "slack_ingest", Json(payload), "pending"),
            )
        
        return job_id
    
    @staticmethod
    def list_recent_jobs(
        limit: int = 10,
        job_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List recent jobs, optionally filtered by type."""
        with DatabaseConnection.get_cursor() as cursor:
            if job_type:
                cursor.execute(
                    """
                    SELECT id, job_type, status, payload, progress, result,
                           created_at, started_at, completed_at, updated_at
                    FROM async_jobs
                    WHERE job_type = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (job_type, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, job_type, status, payload, progress, result,
                           created_at, started_at, completed_at, updated_at
                    FROM async_jobs
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            
            return [
                {
                    "id": row[0],
                    "job_type": row[1],
                    "status": row[2],
                    "payload": row[3] or {},
                    "progress": row[4] or {},
                    "result": row[5] or {},
                    "created_at": row[6],
                    "started_at": row[7],
                    "completed_at": row[8],
                    "updated_at": row[9],
                }
                for row in cursor.fetchall()
            ]
    
    @staticmethod
    def fetch_next_pending_job(job_type: str) -> Optional[Dict[str, Any]]:
        """Atomically claim the next pending job for a worker."""
        with DatabaseConnection.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("BEGIN")
                cursor.execute(
                    """
                    SELECT id, payload
                    FROM async_jobs
                    WHERE status = 'pending' AND job_type = %s
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (job_type,),
                )
                row = cursor.fetchone()
                
                if not row:
                    conn.rollback()
                    return None
                
                job_id, payload = row
                cursor.execute(
                    """
                    UPDATE async_jobs
                    SET status = 'running', started_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (job_id,),
                )
                conn.commit()
                
                return {"id": job_id, "payload": payload}
    
    @staticmethod
    def update_progress(job_id: str, progress: Dict[str, Any]) -> None:
        """Update job progress."""
        with DatabaseConnection.get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE async_jobs
                SET progress = %s, updated_at = NOW()
                WHERE id = %s
                """,
                (Json(progress), job_id),
            )
    
    @staticmethod
    def mark_completed(job_id: str, result: Dict[str, Any]) -> None:
        """Mark a job as completed with result."""
        with DatabaseConnection.get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE async_jobs
                SET status = 'completed', result = %s, completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                (Json(result), job_id),
            )
    
    @staticmethod
    def mark_failed(
        job_id: str,
        error_message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Mark a job as failed with error details."""
        payload = {"error": error_message}
        if details:
            payload["details"] = details
        
        with DatabaseConnection.get_cursor() as cursor:
            cursor.execute(
                """
                UPDATE async_jobs
                SET status = 'failed', result = %s, completed_at = NOW(), updated_at = NOW()
                WHERE id = %s
                """,
                (Json(payload), job_id),
            )
