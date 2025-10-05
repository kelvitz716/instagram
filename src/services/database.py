"""Enhanced database service with optimized session handling."""

import sqlite3
import logging
import asyncio
import queue
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from functools import lru_cache
from collections import defaultdict
from ..core.config import DatabaseConfig

logger = logging.getLogger(__name__)

class SyncConnectionPool:
    """A thread-safe synchronous connection pool for SQLite."""
    
    def __init__(self, database: str, max_connections: int = 5):
        self.database = database
        self.max_connections = max_connections
        self._pool = queue.Queue(maxsize=max_connections)
        self._lock = threading.Lock()
                
    def initialize(self):
        """Initialize the connection pool."""
        with self._lock:
            for _ in range(self.max_connections):
                conn = sqlite3.connect(
                    self.database,
                    isolation_level=None,  # Enable autocommit mode
                    check_same_thread=False  # Allow threads to share connections
                )
                # Enable WAL mode and optimize settings
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=-2000")
                self._pool.put(conn)
    
    def acquire(self) -> sqlite3.Connection:
        """Acquire a connection from the pool."""
        try:
            conn = self._pool.get(timeout=1)
            # Verify connection is still good
            try:
                conn.execute("SELECT 1")
            except (sqlite3.Error, sqlite3.OperationalError):
                # Connection is stale, create a new one
                conn.close()
                conn = sqlite3.connect(
                    self.database,
                    isolation_level=None,
                    check_same_thread=False
                )
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA cache_size=-2000")
            return conn
        except queue.Empty:
            # Create a new connection if pool is empty
            conn = sqlite3.connect(
                self.database,
                isolation_level=None,
                check_same_thread=False
            )
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-2000")
            return conn
    
    def release(self, conn: sqlite3.Connection):
        """Release a connection back to the pool."""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            # If pool is full, close the connection
            conn.close()
    
    def close(self):
        """Close all connections in the pool."""
        with self._lock:
            while not self._pool.empty():
                conn = self._pool.get_nowait()
                conn.close()


class DatabaseService:
    """Handles all database operations with optimized performance."""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.db_path = config.path  # Already a Path object
        self._pool = None
        self._prepared_statements: Dict[str, str] = {}
        self._stats_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 60  # Cache TTL in seconds
        
    async def initialize(self):
        """Initialize the database with optimized settings."""
        # Create connection pool
        self._pool = SyncConnectionPool(self.db_path, self.config.pool_size)
        self._pool.initialize()
        
        conn = self._pool.acquire()
        try:
            await self._create_telegram_sessions_table(conn)
            await self._prepare_statements(conn)
        finally:
            self._pool.release(conn)

    async def _create_telegram_sessions_table(self, conn: sqlite3.Connection):
        """Create telegram-related tables."""
        # Create sessions table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_name TEXT NOT NULL,
                session_file_path TEXT NOT NULL,
                session_data TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create auth state table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_auth_state (
                phone_number TEXT PRIMARY KEY,
                phone_code_hash TEXT NOT NULL,
                next_step TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create indexes
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_sessions_active 
            ON telegram_sessions(is_active, expires_at)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_sessions_name 
            ON telegram_sessions(session_name)
        """)
        
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_sessions_unique_active 
            ON telegram_sessions(session_name) WHERE is_active = TRUE
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_auth_state_updated 
            ON telegram_auth_state(updated_at)
        """)
        
    async def _prepare_statements(self, conn: sqlite3.Connection):
        """Prepare common SQL statements."""
        statements = {
            'insert_telegram_session': """
                INSERT INTO telegram_sessions (
                    session_name, session_file_path, session_data, phone_number,
                    is_active, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            'get_active_telegram_session': """
                SELECT id, session_name, session_file_path, session_data, phone_number,
                       is_active, expires_at, created_at, updated_at
                FROM telegram_sessions 
                WHERE is_active = TRUE 
                AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                ORDER BY updated_at DESC 
                LIMIT 1
            """,
            'deactivate_telegram_sessions': """
                UPDATE telegram_sessions 
                SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE session_name = ?
            """,
            'cleanup_expired_telegram_sessions': """
                DELETE FROM telegram_sessions 
                WHERE expires_at IS NOT NULL AND expires_at < CURRENT_TIMESTAMP
            """
        }
        
        for name, stmt in statements.items():
            self._prepared_statements[name] = stmt

    async def save_auth_state(self, phone_number: str, phone_code_hash: str, next_step: str) -> None:
        """Save Telegram authentication state.
        
        Args:
            phone_number: The phone number being authenticated
            phone_code_hash: The hash returned by send_code_request
            next_step: The next authentication step required
        """
        conn = self._pool.acquire()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO telegram_auth_state 
                (phone_number, phone_code_hash, next_step, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (phone_number, phone_code_hash, next_step))
        finally:
            self._pool.release(conn)

    async def get_auth_state(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Get current authentication state for a phone number.
        
        Args:
            phone_number: The phone number to look up
            
        Returns:
            dict: Authentication state if exists, None otherwise
        """
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                "SELECT * FROM telegram_auth_state WHERE phone_number = ?",
                (phone_number,)
            )
            row = cursor.fetchone()
            if row:
                return dict(zip([col[0] for col in cursor.description], row))
            return None
        finally:
            self._pool.release(conn)

    async def clear_auth_state(self, phone_number: str) -> None:
        """Clear authentication state after successful login.
        
        Args:
            phone_number: The phone number to clear auth state for
        """
        conn = self._pool.acquire()
        try:
            conn.execute(
                "DELETE FROM telegram_auth_state WHERE phone_number = ?",
                (phone_number,)
            )
        finally:
            self._pool.release(conn)

    async def store_telegram_session(self, session_name: str, session_file_path: str,
                                   session_data: str, phone_number: str,
                                   is_active: bool = True, expires_at: Optional[datetime] = None) -> int:
        """Store a Telegram session in the database.
        
        Args:
            session_name: Name of the session (e.g., 'telegram_bot_session')
            session_file_path: Path to the .session file
            session_data: JSON string containing session metadata
            phone_number: Phone number used for authentication
            is_active: Whether this session is currently active
            expires_at: When the session expires (optional)
            
        Returns:
            int: Session ID
        """
        conn = self._pool.acquire()
        try:
            # First, deactivate any existing sessions if this one should be active
            if is_active:
                conn.execute(
                    self._prepared_statements['deactivate_telegram_sessions'],
                    (session_name,)
                )
            
            # Insert new session
            cursor = conn.execute(
                self._prepared_statements['insert_telegram_session'],
                (session_name, session_file_path, session_data, phone_number, is_active, expires_at)
            )
            
            return cursor.lastrowid
        finally:
            self._pool.release(conn)

    async def get_active_telegram_session(self) -> Optional[Dict[str, Any]]:
        """Get the active Telegram session.
        
        Returns:
            Dict containing session information or None if no active session
        """
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['get_active_telegram_session']
            )
            
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'session_name': row[1], 
                    'session_file_path': row[2],
                    'session_data': row[3],
                    'phone_number': row[4],
                    'is_active': bool(row[5]),
                    'expires_at': row[6],
                    'created_at': row[7],
                    'updated_at': row[8]
                }
            return None
        finally:
            self._pool.release(conn)

    async def update_telegram_session(self, session_id: int, **kwargs) -> bool:
        """Update a Telegram session record.
        
        Args:
            session_id: ID of the session to update
            **kwargs: Fields to update (session_data, is_active, expires_at)
            
        Returns:
            bool: True if update was successful
        """
        if not kwargs:
            return False
            
        # Build update query dynamically
        set_clauses = []
        values = []
        
        for field, value in kwargs.items():
            if field in ['session_data', 'is_active', 'expires_at']:
                set_clauses.append(f"{field} = ?")
                values.append(value)
        
        if not set_clauses:
            return False
            
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")
        values.append(session_id)
        
        query = f"""
            UPDATE telegram_sessions 
            SET {', '.join(set_clauses)}
            WHERE id = ?
        """
        
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(query, values)
            return cursor.rowcount > 0
        finally:
            self._pool.release(conn)

    async def cleanup_expired_telegram_sessions(self) -> int:
        """Clean up expired Telegram sessions.
        
        Returns:
            int: Number of sessions cleaned up
        """
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['cleanup_expired_telegram_sessions']
            )
            return cursor.rowcount
        finally:
            self._pool.release(conn)

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None
            self._stats_cache.clear()