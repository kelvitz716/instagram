import sqlite3
import logging
import asyncio
import queue
import threading
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
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
        self.db_path = Path(config.db_path)
        self._pool = None
        self._prepared_statements: Dict[str, str] = {}
        self._stats_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 60  # Cache TTL in seconds
        
    async def _prepare_statements(self, conn: sqlite3.Connection):
        """Prepare common SQL statements."""
        statements = {
            'insert_download': """
                INSERT INTO downloads (url, status, file_paths, error)
                VALUES (?, ?, ?, ?)
            """,
            'update_download': """
                UPDATE downloads 
                SET status = ?, file_paths = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
            'insert_upload': """
                INSERT INTO uploads (download_id, file_path, status, message_id, error)
                VALUES (?, ?, ?, ?, ?)
            """,
            'update_upload': """
                UPDATE uploads 
                SET status = ?, message_id = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
            'insert_operation': """
                INSERT INTO file_operations 
                (file_path, file_size, operation_type, success, error)
                VALUES (?, ?, ?, ?, ?)
            """
        }
        
        for name, stmt in statements.items():
            self._prepared_statements[name] = stmt
    
    async def _create_telegram_sessions_table(self, conn: sqlite3.Connection):
        """Create the telegram_sessions table."""
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
        
        # Create indexes for better performance
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_sessions_active 
            ON telegram_sessions(is_active, expires_at)
        """)
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_telegram_sessions_name 
            ON telegram_sessions(session_name)
        """)

    async def initialize(self):
        """Initialize the database with optimized settings."""
        # Create connection pool
        self._pool = SyncConnectionPool(self.db_path, self.config.pool_size)
        self._pool.initialize()
        
        conn = self._pool.acquire()
        try:
            # Create tables with optimized indexes
            conn.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    file_paths TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_url ON downloads(url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS uploads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    download_id INTEGER,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message_id INTEGER,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (download_id) REFERENCES downloads (id)
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_download_id ON uploads(download_id)")
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    operation_type TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS download_state (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    files TEXT NOT NULL,  -- JSON array of file paths
                    status TEXT NOT NULL DEFAULT 'pending',
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status_message_id INTEGER,
                    chat_id INTEGER,
                    error TEXT,
                    completed BOOLEAN DEFAULT 0,
                    UNIQUE(url, status_message_id)
                )
            """)
            
            # Create Instagram session tables
            conn.execute("""
                CREATE TABLE IF NOT EXISTS instagram_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT NOT NULL,
                    session_type TEXT NOT NULL,
                    cookies_file_path TEXT,
                    session_data TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 0,
                    last_validated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER NOT NULL,
                    is_valid BOOLEAN NOT NULL,
                    error_message TEXT,
                    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES instagram_sessions (id)
                )
            """)
            
            # Create Telegram sessions table
            await self._create_telegram_sessions_table(conn)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_type ON file_operations(operation_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_state_status ON download_state(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_state_completed ON download_state(completed)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_active ON instagram_sessions(user_id, is_active)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON instagram_sessions(expires_at)")
            
            # Prepare statements
            await self._prepare_statements(conn)
            
            # Prepare Instagram session statements
            statements = {
                'insert_session': """
                    INSERT INTO instagram_sessions 
                    (user_id, username, session_type, cookies_file_path, session_data, 
                     is_active, last_validated, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                'update_session': """
                    UPDATE instagram_sessions 
                    SET session_data = ?, is_active = ?, last_validated = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP, expires_at = ?
                    WHERE id = ?
                """,
                'insert_validation': """
                    INSERT INTO session_validations 
                    (session_id, is_valid, error_message)
                    VALUES (?, ?, ?)
                """,
                'get_active_session': """
                    SELECT id, session_type, cookies_file_path, session_data, last_validated
                    FROM instagram_sessions
                    WHERE user_id = ? AND is_active = 1
                    ORDER BY last_validated DESC
                    LIMIT 1
                """,
                'get_all_sessions': """
                    SELECT id, session_type, cookies_file_path, session_data, is_active, 
                           last_validated, created_at, expires_at
                    FROM instagram_sessions
                    WHERE user_id = ?
                    ORDER BY is_active DESC, last_validated DESC
                """,
                'delete_session': """
                    DELETE FROM instagram_sessions WHERE id = ?
                """,
                'cleanup_expired_sessions': """
                    DELETE FROM instagram_sessions 
                    WHERE expires_at < CURRENT_TIMESTAMP
                      OR (last_validated < datetime('now', '-7 days') AND NOT is_active)
                """
            }
            self._prepared_statements.update(statements)
            
            # Prepare Telegram session statements
            telegram_statements = {
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
            self._prepared_statements.update(telegram_statements)
            
        finally:
            self._pool.release(conn)
    
    @lru_cache(maxsize=1000)
    async def get_download_status(self, url: str) -> Optional[Dict[str, Any]]:
        """Get the status of a download by URL with caching."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                "SELECT * FROM downloads WHERE url = ? ORDER BY created_at DESC LIMIT 1",
                (url,)
            )
            row = cursor.fetchone()
            if row:
                return dict(zip([col[0] for col in cursor.description], row))
            return None
        finally:
            self._pool.release(conn)

    async def get_statistics(self) -> Dict[str, Any]:
        """Get bot statistics from database with caching."""
        current_time = datetime.now().timestamp()
        
        # Check cache
        if 'stats' in self._stats_cache:
            stats, timestamp = self._stats_cache['stats']
            if current_time - timestamp < self._cache_ttl:
                return stats
        
        conn = self._pool.acquire()
        try:
            stats = defaultdict(int)
            
            # First check if tables exist and have the required columns
            cursor = conn.execute("""
                SELECT COUNT(*) FROM sqlite_master 
                WHERE type='table' AND name IN ('downloads', 'uploads', 'file_operations')
            """)
            table_count = cursor.fetchone()[0]
            if table_count < 3:
                # Tables don't exist yet
                return dict(stats)
                
            # Use a single query for better performance, with proper status checks
            # Using COALESCE to ensure we don't get null values
            cursor = conn.execute("""
                SELECT 
                    COALESCE((SELECT COUNT(*) FROM downloads), 0) as total_downloads,
                    COALESCE((SELECT COUNT(*) FROM downloads WHERE status = 'success'), 0) as successful_downloads,
                    COALESCE((SELECT COUNT(*) FROM downloads WHERE status = 'failed'), 0) as failed_downloads,
                    COALESCE((SELECT COUNT(*) FROM uploads), 0) as total_uploads,
                    COALESCE((SELECT COUNT(*) FROM uploads WHERE status = 'success'), 0) as successful_uploads,
                    COALESCE((SELECT COUNT(*) FROM uploads WHERE status = 'failed'), 0) as failed_uploads,
                    COALESCE((SELECT COUNT(DISTINCT file_path) FROM file_operations WHERE operation_type = 'download'), 0) as total_files_downloaded,
                    COALESCE((SELECT COUNT(DISTINCT file_path) FROM file_operations WHERE operation_type = 'upload' AND success = 1), 0) as successful_file_uploads,
                    COALESCE((SELECT SUM(file_size) FROM file_operations WHERE operation_type = 'download'), 0) as total_bytes_downloaded
            """)
            row = cursor.fetchone()
            if row:
                col_names = [col[0] for col in cursor.description]
                stats.update(dict(zip(col_names, row)))
            
            # Cache the results
            self._stats_cache['stats'] = (dict(stats), current_time)
            return dict(stats)
        finally:
            self._pool.release(conn)
            
    # Instagram session management methods
    
    async def store_instagram_session(self, user_id: int, username: str, 
                                    session_type: str, session_data: str,
                                    cookies_file_path: Optional[str] = None,
                                    make_active: bool = True,
                                    expires_at: Optional[datetime] = None) -> int:
        """Store a new Instagram session."""
        conn = self._pool.acquire()
        try:
            # First, deactivate and remove any existing sessions of the same type for this user
            conn.execute("""
                DELETE FROM instagram_sessions 
                WHERE user_id = ? AND session_type = ? AND cookies_file_path = ?
            """, (user_id, session_type, cookies_file_path))
            
            if make_active:
                # Deactivate other sessions for this user
                conn.execute(
                    "UPDATE instagram_sessions SET is_active = 0 WHERE user_id = ?",
                    (user_id,)
                )
            
            cursor = conn.execute(
                self._prepared_statements['insert_session'],
                (user_id, username, session_type, cookies_file_path, 
                 session_data, make_active, expires_at)
            )
            return cursor.lastrowid
        finally:
            self._pool.release(conn)
    
    async def get_active_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the active session for a user."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['get_active_session'],
                (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'session_type': row[1],
                    'cookies_file_path': row[2],
                    'session_data': row[3],
                    'last_validated': row[4]
                }
            return None
        finally:
            self._pool.release(conn)
    
    async def get_all_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['get_all_sessions'],
                (user_id,)
            )
            rows = cursor.fetchall()
            return [{
                'id': row[0],
                'session_type': row[1],
                'cookies_file_path': row[2],
                'session_data': row[3],
                'is_active': bool(row[4]),
                'last_validated': row[5],
                'created_at': row[6],
                'expires_at': row[7]
            } for row in rows]
        finally:
            self._pool.release(conn)
    
    async def update_session(self, session_id: int, session_data: str,
                           is_active: bool, expires_at: Optional[datetime] = None) -> bool:
        """Update an existing session."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['update_session'],
                (session_data, is_active, expires_at, session_id)
            )
            return cursor.rowcount > 0
        finally:
            self._pool.release(conn)
    
    async def delete_session(self, session_id: int) -> bool:
        """Delete a session."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['delete_session'],
                (session_id,)
            )
            return cursor.rowcount > 0
        finally:
            self._pool.release(conn)
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions. Returns number of deleted sessions."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['cleanup_expired_sessions']
            )
            return cursor.rowcount
        finally:
            self._pool.release(conn)
    
    async def log_session_validation(self, session_id: int, 
                                   is_valid: bool, 
                                   error_message: Optional[str] = None):
        """Log a session validation attempt."""
        conn = self._pool.acquire()
        try:
            conn.execute(
                self._prepared_statements['insert_validation'],
                (session_id, is_valid, error_message)
            )
        finally:
            self._pool.release(conn)
    
    # Telegram session management methods
    
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
            
    async def get_content_type_stats(self) -> Dict[str, int]:
        """Get download statistics broken down by content type.
        
        Returns:
            Dict[str, int]: A dictionary mapping content types to their download counts
        """
        # Check cache first
        current_time = datetime.now().timestamp()
        if 'content_stats' in self._stats_cache:
            stats, timestamp = self._stats_cache['content_stats']
            if current_time - timestamp < self._cache_ttl:
                return stats
                
        conn = self._pool.acquire()
        try:
            # Query the downloads table and extract content types from URLs
            cursor = conn.execute("""
                SELECT 
                    CASE
                        WHEN url LIKE '%instagram.com/p/%' THEN 'post'
                        WHEN url LIKE '%instagram.com/reel/%' THEN 'reel'
                        WHEN url LIKE '%instagram.com/stories/%' THEN 'story'
                        WHEN url LIKE '%instagram.com/stories/highlights/%' THEN 'highlight'
                        WHEN url LIKE '%instagram.com/tv/%' THEN 'tv'
                        ELSE 'other'
                    END as content_type,
                    COUNT(*) as count
                FROM downloads
                WHERE status = 'success'
                GROUP BY content_type
                ORDER BY count DESC
            """)
            
            stats = {}
            for row in cursor.fetchall():
                stats[row[0]] = row[1]
                
            # Cache the results
            self._stats_cache['content_stats'] = (stats, current_time)
            
            return stats
        finally:
            self._pool.release(conn)

    async def record_download(
        self, 
        url: str, 
        status: str = "pending",
        file_paths: Optional[List[str]] = None,
        error: Optional[str] = None
    ) -> int:
        """Record a new download attempt with prepared statement."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute(
                self._prepared_statements['insert_download'],
                (url, status, ','.join(file_paths) if file_paths else None, error)
            )
            
            # Clear stats cache to ensure fresh data
            self._stats_cache.clear()
            
            return cursor.lastrowid
        finally:
            self._pool.release(conn)

    async def batch_log_operations(self, operations: List[Tuple[str, int, str, bool, Optional[str]]]):
        """Batch log multiple file operations for better performance."""
        conn = self._pool.acquire()
        try:
            conn.executemany(
                self._prepared_statements['insert_operation'],
                operations
            )
        finally:
            self._pool.release(conn)

    async def log_file_operation(
        self, 
        file_path: str, 
        file_size: int, 
        operation_type: str,
        success: bool,
        error: Optional[str] = None
    ) -> None:
        """Log a file operation with optimized single-query insert."""
        await self.batch_log_operations([(file_path, file_size, operation_type, success, error)])

    async def save_download_state(self, state: Dict[str, Any]) -> None:
        """
        Save download state for potential recovery.
        
        Args:
            state: Dict containing:
                - url: str - The download URL
                - files: List[str] - List of downloaded file paths
                - timestamp: str - ISO format timestamp
                - status_message_id: Optional[int] - ID of the status message
                - chat_id: Optional[int] - Chat ID where the download was initiated
        """
        files_str = ','.join(state['files'])  # Convert list to comma-separated string
        
        conn = self._pool.acquire()
        try:
            conn.execute("""
                INSERT INTO download_state 
                (url, files, timestamp, status_message_id, chat_id, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(url, status_message_id) 
                DO UPDATE SET 
                    files=excluded.files,
                    timestamp=excluded.timestamp,
                    status='pending'
            """, (
                state['url'],
                files_str,
                state['timestamp'],
                state.get('status_message_id'),
                state.get('chat_id'),
                'pending'
            ))
        finally:
            self._pool.release(conn)

    async def get_pending_downloads(self) -> List[Dict[str, Any]]:
        """
        Get list of downloads that need recovery.
        
        Returns:
            List of download states that were interrupted
        """
        conn = self._pool.acquire()
        try:
            cursor = conn.execute("""
                SELECT * FROM download_state 
                WHERE completed = 0 
                AND status = 'pending'
                AND timestamp > datetime('now', '-1 day')
                ORDER BY timestamp DESC
            """)
            
            results = []
            for row in cursor.fetchall():
                state = dict(zip([col[0] for col in cursor.description], row))
                # Convert files string back to list
                state['files'] = state['files'].split(',') if state['files'] else []
                results.append(state)
                
            return results
        finally:
            self._pool.release(conn)

    async def mark_download_completed(self, url: str, status_message_id: Optional[int] = None) -> None:
        """Mark a download as completed."""
        conn = self._pool.acquire()
        try:
            if status_message_id is not None:
                conn.execute("""
                    UPDATE download_state 
                    SET completed = 1, status = 'completed'
                    WHERE url = ? AND status_message_id = ?
                """, (url, status_message_id))
            else:
                conn.execute("""
                    UPDATE download_state 
                    SET completed = 1, status = 'completed'
                    WHERE url = ?
                """, (url,))
        finally:
            self._pool.release(conn)

    async def mark_download_failed(self, url: str, error: str, status_message_id: Optional[int] = None) -> None:
        """Mark a download as failed with error information."""
        conn = self._pool.acquire()
        try:
            if status_message_id is not None:
                conn.execute("""
                    UPDATE download_state 
                    SET status = 'failed', error = ?, completed = 1
                    WHERE url = ?
                """, (error, url))
        finally:
            self._pool.release(conn)

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            self._pool.close()
            self._pool = None
            self._stats_cache.clear()d = 1
                    WHERE url = ? AND status_message_id = ?
                """, (error, url, status_message_id))
            else:
                conn.execute("""
                    UPDATE download_state 
                    SET status = 'failed', error = ?, complete