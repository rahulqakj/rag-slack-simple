"""
Base utilities and shared infrastructure for core services.
"""
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, List, Optional, TypeVar

import psycopg2
from psycopg2 import pool
from pgvector.psycopg2 import register_vector
from psycopg2.extras import register_uuid


T = TypeVar("T")
logger = logging.getLogger(__name__)


class ServiceError(Exception):
    """Base exception for service layer errors."""


@dataclass(frozen=True)
class EmbeddingVector:
    """Wrapper for embedding vectors with utility methods."""
    values: List[float]

    def to_pg_literal(self) -> str:
        """Convert to PostgreSQL vector literal format."""
        return "[" + ",".join(map(str, self.values)) + "]"

    @classmethod
    def from_list(cls, values: Optional[List[float]]) -> Optional["EmbeddingVector"]:
        """Create from list, returning None if input is None or empty."""
        if not values:
            return None
        return cls(values=values)


class DatabaseConnection:
    """
    Database connection manager with connection pooling support.
    
    Usage:
        with DatabaseConnection.get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(...)
    """
    
    _connection_params: Optional[dict] = None
    _pool: Optional[pool.ThreadedConnectionPool] = None
    _pool_min_conn: int = 2
    _pool_max_conn: int = 10
    
    @classmethod
    def configure(
        cls,
        host: str,
        port: str,
        dbname: str,
        user: str,
        password: str,
        min_conn: int = 2,
        max_conn: int = 10,
    ) -> None:
        """Configure database connection parameters and initialize pool."""
        cls._connection_params = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
        }
        cls._pool_min_conn = min_conn
        cls._pool_max_conn = max_conn
        cls._pool = None  # Reset pool on reconfigure
    
    @classmethod
    def _get_params(cls) -> dict:
        """Get connection parameters, raising if not configured."""
        if cls._connection_params is None:
            raise ServiceError("Database not configured. Call DatabaseConnection.configure() first.")
        return cls._connection_params
    
    @classmethod
    def _get_pool(cls) -> pool.ThreadedConnectionPool:
        """Get or create the connection pool."""
        if cls._pool is None:
            params = cls._get_params()
            cls._pool = pool.ThreadedConnectionPool(
                minconn=cls._pool_min_conn,
                maxconn=cls._pool_max_conn,
                **params
            )
            logger.info(
                "Connection pool initialized (min=%d, max=%d)",
                cls._pool_min_conn,
                cls._pool_max_conn
            )
        return cls._pool
    
    @classmethod
    def close_pool(cls) -> None:
        """Close all connections in the pool."""
        if cls._pool is not None:
            cls._pool.closeall()
            cls._pool = None
            logger.info("Connection pool closed")
    
    @classmethod
    @contextmanager
    def get_connection(cls, autocommit: bool = False) -> Generator[psycopg2.extensions.connection, None, None]:
        """
        Context manager for database connections from the pool.
        
        Args:
            autocommit: If True, each statement is auto-committed
            
        Yields:
            psycopg2 connection with pgvector and UUID support registered
        """
        connection_pool = cls._get_pool()
        conn = None
        try:
            conn = connection_pool.getconn()
            conn.autocommit = autocommit
            register_vector(conn)
            register_uuid(conn)
            yield conn
            if not autocommit:
                conn.commit()
        except Exception:
            if conn and not autocommit:
                conn.rollback()
            raise
        finally:
            if conn:
                connection_pool.putconn(conn)

    @classmethod
    @contextmanager
    def get_cursor(cls) -> Generator[psycopg2.extensions.cursor, None, None]:
        """Convenience method to get a cursor with auto-managed connection."""
        with cls.get_connection() as conn:
            with conn.cursor() as cursor:
                yield cursor

