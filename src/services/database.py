import sqlite3
import logging
import asyncio
import queue
import threading
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime, timedelta
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(url, status_message_id)
                )
            """)
            
            conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_type ON file_operations(operation_type)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_state_status ON download_state(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_download_state_completed ON download_state(completed)")
            
            # Create the all_files view that combines unique files from both tables
            conn.execute("""
                CREATE VIEW IF NOT EXISTS all_files AS 
                SELECT DISTINCT file_path 
                FROM (
                    SELECT file_path 
                    FROM file_operations 
                    WHERE success = 1 AND operation_type = 'download'
                    UNION 
                    SELECT value as file_path
                    FROM download_state, json_each(files) 
                    WHERE status = 'completed' AND completed = 1 AND json_valid(files)
                )
            """)
            
            # Prepare statements
            await self._prepare_statements(conn)
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

    async def get_content_type_stats(self) -> Dict[str, int]:
        """Get statistics about different types of content downloaded."""
        conn = self._pool.acquire()
        try:
            cursor = conn.execute("""
                SELECT 
                    CASE 
                        WHEN file_path LIKE '%.jpg' OR file_path LIKE '%.jpeg' OR file_path LIKE '%.png' THEN 'images'
                        WHEN file_path LIKE '%.mp4' OR file_path LIKE '%.mov' THEN 'videos'
                        WHEN file_path LIKE '%.gif' THEN 'gifs'
                        ELSE 'other'
                    END as content_type,
                    COUNT(*) as count
                FROM file_operations 
                WHERE operation_type = 'download' 
                AND success = 1
                GROUP BY content_type
            """)
            return dict(cursor.fetchall())
        finally:
            self._pool.release(conn)

    async def get_statistics(self) -> Dict[str, Any]:
        """Get detailed bot statistics with corrected counting."""
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
            # Calculate time ranges
            cursor = conn.execute("""
                WITH RECURSIVE time_ranges AS (
                    SELECT 
                        datetime('now', '-1 hour') as last_hour,
                        datetime('now', '-1 day') as last_24h,
                        datetime('now', '-7 days') as last_7d,
                        datetime('now', 'start of month') as this_month,
                        datetime('now', '-30 days') as last_30d
                ),
                download_stats AS (
                    SELECT 
                        COUNT(DISTINCT url) as total_attempts,
                        COUNT(DISTINCT CASE WHEN status = 'completed' AND completed = 1 THEN url END) as successful_downloads,
                        COUNT(DISTINCT CASE WHEN status = 'failed' OR (status != 'completed' AND completed = 1) THEN url END) as failed_downloads,
                        CASE 
                            WHEN COUNT(DISTINCT url) > 0 
                            THEN ROUND(COUNT(DISTINCT CASE WHEN status = 'completed' AND completed = 1 THEN url END) * 100.0 / COUNT(DISTINCT url), 1)
                            ELSE 0 
                        END as success_rate
                    FROM download_state 
                    WHERE created_at >= (SELECT last_30d FROM time_ranges)
                    AND (status != 'pending' OR completed = 1)
                ),
                recent_activity AS (
                    SELECT
                        COALESCE(SUM(CASE WHEN created_at >= tr.last_hour AND status = 'completed' AND completed = 1 THEN 1 ELSE 0 END), 0) as downloads_last_hour,
                        COALESCE(SUM(CASE WHEN created_at >= tr.last_24h AND status = 'completed' AND completed = 1 THEN 1 ELSE 0 END), 0) as downloads_last_24h,
                        COALESCE(SUM(CASE WHEN created_at >= tr.last_7d AND status = 'completed' AND completed = 1 THEN 1 ELSE 0 END), 0) as downloads_last_7d,
                        COALESCE(SUM(CASE WHEN created_at >= tr.this_month AND status = 'completed' AND completed = 1 THEN 1 ELSE 0 END), 0) as downloads_this_month
                    FROM download_state
                    CROSS JOIN time_ranges tr
                ),
                file_stats AS (
                    SELECT 
                        tr.last_hour,
                        tr.last_24h,
                        (SELECT COUNT(DISTINCT file_path) 
                         FROM all_files) as total_files_downloaded,
                        COUNT(DISTINCT CASE WHEN operation_type = 'upload' AND success = 1 
                              THEN file_path || created_at END) as successful_file_uploads,
                        COUNT(DISTINCT CASE WHEN operation_type = 'upload' AND success = 0 
                              THEN file_path || created_at END) as failed_uploads,
                        COALESCE(SUM(CASE WHEN operation_type = 'download' AND success = 1 
                                    THEN file_size ELSE 0 END), 0) as total_bytes_downloaded,
                        COALESCE(SUM(CASE WHEN operation_type = 'download' AND success = 1 AND created_at >= tr.last_hour 
                                    THEN file_size ELSE 0 END), 0) as bytes_last_hour,
                        COALESCE(SUM(CASE WHEN operation_type = 'download' AND success = 1 AND created_at >= tr.last_24h 
                                    THEN file_size ELSE 0 END), 0) as bytes_last_24h,
                        COUNT(CASE WHEN operation_type = 'upload' THEN 1 END) as total_uploads,
                        COUNT(CASE WHEN operation_type = 'upload' AND success = 1 THEN 1 END) as successful_uploads,
                        COUNT(CASE WHEN operation_type = 'upload' AND success = 0 THEN 1 END) as failed_uploads,
                        CASE 
                            WHEN COUNT(CASE WHEN operation_type = 'upload' THEN 1 END) > 0 
                            THEN ROUND(COUNT(CASE WHEN operation_type = 'upload' AND success = 1 THEN 1 END) * 100.0 
                                     / COUNT(CASE WHEN operation_type = 'upload' THEN 1 END), 1)
                            ELSE 0 
                        END as upload_success_rate,
                        ROUND(AVG(CASE WHEN success = 1 THEN file_size END), 0) as avg_file_size
                    FROM file_operations, time_ranges tr
                    GROUP BY tr.last_hour, tr.last_24h
                )
                SELECT 
                    d.*,
                    r.*,
                    f.*
                FROM download_stats d
                CROSS JOIN recent_activity r
                CROSS JOIN file_stats f
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
            # Insert into download_state for better tracking
            files_str = f'["{",".join(file_paths)}"]' if file_paths else '[]'
            cursor = conn.execute("""
                INSERT INTO download_state 
                (url, files, status, completed, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                url,
                files_str,
                status,
                1 if status == 'completed' else 0
            ))
            
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
        conn = self._pool.acquire()
        try:
            # Clear stats cache to ensure fresh data
            self._stats_cache.clear()
            
            # For downloads, insert both attempt and result
            if operation_type == 'download':
                # First log the attempt
                conn.execute("""
                    INSERT INTO file_operations 
                    (file_path, file_size, operation_type, success, error, created_at)
                    VALUES (?, ?, 'download_attempt', 1, NULL, CURRENT_TIMESTAMP)
                """, (file_path, file_size))
                
                # Then log the result
                conn.execute("""
                    INSERT INTO file_operations 
                    (file_path, file_size, operation_type, success, error, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (file_path, file_size, operation_type, success, error))
            else:
                # For other operations, just log the operation
                conn.execute("""
                    INSERT INTO file_operations 
                    (file_path, file_size, operation_type, success, error, created_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (file_path, file_size, operation_type, success, error))
            
            # Clear stats cache to ensure fresh data
            self._stats_cache.clear()
            
            # If it's a successful download, update the download state
            if operation_type == 'download' and success:
                conn.execute("""
                    UPDATE download_state 
                    SET status = 'completed', 
                        completed = 1,
                        timestamp = CURRENT_TIMESTAMP
                    WHERE url IN (
                        SELECT url 
                        FROM download_state 
                        WHERE json_array_length(files) > 0
                        AND json_extract(files, '$[#-1]') = ?
                        ORDER BY created_at DESC 
                        LIMIT 1
                    )
                """, (file_path,))
        finally:
            self._pool.release(conn)

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
        # Clear stats cache to ensure fresh data
        self._stats_cache.clear()
        
        # Convert files list to JSON array string
        files_str = f'["{",".join(state["files"])}"]'
        
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
                import json
            results = []
            for row in cursor.fetchall():
                state = dict(zip([col[0] for col in cursor.description], row))
                # Convert JSON array string back to list
                try:
                    state['files'] = json.loads(state['files']) if state['files'] else []
                    results.append(state)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode files JSON: {e}")
                    continue  # Skip malformed records
                
            return results
        finally:
            self._pool.release(conn)

    async def mark_download_completed(self, url: str, status_message_id: Optional[int] = None) -> None:
        """Mark a download as completed."""
        conn = self._pool.acquire()
        try:
            # Clear stats cache to ensure fresh data
            self._stats_cache.clear()
            
            if status_message_id is not None:
                conn.execute("""
                    UPDATE download_state 
                    SET completed = 1, 
                        status = 'completed',
                        timestamp = CURRENT_TIMESTAMP
                    WHERE url = ? AND status_message_id = ?
                """, (url, status_message_id))
            else:
                conn.execute("""
                    UPDATE download_state 
                    SET completed = 1, 
                        status = 'completed',
                        timestamp = CURRENT_TIMESTAMP
                    WHERE url = ? AND completed = 0
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
                    WHERE url = ? AND status_message_id = ?
                """, (error, url, status_message_id))
            else:
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
            self._stats_cache.clear()
