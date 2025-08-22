import aiosqlite
import logging
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from datetime import datetime
from functools import lru_cache
from collections import defaultdict
from ..core.config import DatabaseConfig

logger = logging.getLogger(__name__)

class ConnectionPool:
    """A simple async connection pool for SQLite."""
    
    def __init__(self, database: str, max_connections: int = 5):
        self.database = database
        self.max_connections = max_connections
        self._pool: List[aiosqlite.Connection] = []
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_connections)
    
    async def initialize(self):
        """Initialize the connection pool."""
        async with self._lock:
            for _ in range(self.max_connections):
                conn = await aiosqlite.connect(self.database)
                await conn.execute("PRAGMA journal_mode=WAL")  # Enable Write-Ahead Logging
                await conn.execute("PRAGMA synchronous=NORMAL")  # Optimize synchronization
                await conn.execute("PRAGMA cache_size=-2000")  # Set cache to 2MB
                self._pool.append(conn)
    
    async def acquire(self) -> aiosqlite.Connection:
        """Acquire a connection from the pool."""
        await self._semaphore.acquire()
        async with self._lock:
            if not self._pool:
                conn = await aiosqlite.connect(self.database)
            else:
                conn = self._pool.pop()
        return conn
    
    async def release(self, conn: aiosqlite.Connection):
        """Release a connection back to the pool."""
        async with self._lock:
            self._pool.append(conn)
        self._semaphore.release()
    
    async def close(self):
        """Close all connections in the pool."""
        async with self._lock:
            while self._pool:
                conn = self._pool.pop()
                await conn.close()

class DatabaseService:
    """Handles all database operations with optimized performance."""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.db_path = Path(config.db_path)
        self._pool = None
        self._prepared_statements: Dict[str, str] = {}
        self._stats_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 60  # Cache TTL in seconds
        
    async def _prepare_statements(self, conn: aiosqlite.Connection):
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
        self._pool = ConnectionPool(self.db_path, self.config.pool_size)
        await self._pool.initialize()
        
        async with await self._pool.acquire() as conn:
            # Enable WAL mode and optimize settings
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA cache_size=-2000")
            
            # Create tables with optimized indexes
            await conn.execute("""
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
            
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_url ON downloads(url)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status)")
            
            await conn.execute("""
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
            
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_status ON uploads(status)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_uploads_download_id ON uploads(download_id)")
            
            await conn.execute("""
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
            
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_operations_type ON file_operations(operation_type)")
            await conn.commit()
            
            # Prepare statements
            await self._prepare_statements(conn)
    
    @lru_cache(maxsize=1000)
    async def get_download_status(self, url: str) -> Optional[Dict[str, Any]]:
        """Get the status of a download by URL with caching."""
        async with await self._pool.acquire() as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT * FROM downloads WHERE url = ? ORDER BY created_at DESC LIMIT 1",
                (url,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_statistics(self) -> Dict[str, Any]:
        """Get bot statistics from database with caching."""
        current_time = datetime.now().timestamp()
        
        # Check cache
        if 'stats' in self._stats_cache:
            stats, timestamp = self._stats_cache['stats']
            if current_time - timestamp < self._cache_ttl:
                return stats
        
        async with await self._pool.acquire() as conn:
            conn.row_factory = aiosqlite.Row
            stats = defaultdict(int)
            
            # Use a single query for better performance
            async with conn.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM downloads) as total_downloads,
                    (SELECT COUNT(*) FROM downloads WHERE status = 'success') as successful_downloads,
                    (SELECT COUNT(*) FROM downloads WHERE status = 'failed') as failed_downloads,
                    (SELECT COUNT(*) FROM uploads) as total_uploads,
                    (SELECT COUNT(*) FROM uploads WHERE status = 'success') as successful_uploads,
                    (SELECT COUNT(*) FROM uploads WHERE status = 'failed') as failed_uploads
            """) as cursor:
                row = await cursor.fetchone()
                if row:
                    stats.update(dict(row))
            
            # Cache the results
            self._stats_cache['stats'] = (dict(stats), current_time)
            return dict(stats)

    async def record_download(
        self, 
        url: str, 
        status: str = "pending",
        file_paths: Optional[List[str]] = None,
        error: Optional[str] = None
    ) -> int:
        """Record a new download attempt with prepared statement."""
        async with await self._pool.acquire() as conn:
            cursor = await conn.execute(
                self._prepared_statements['insert_download'],
                (url, status, ','.join(file_paths) if file_paths else None, error)
            )
            await conn.commit()
            return cursor.lastrowid

    async def batch_log_operations(self, operations: List[Tuple[str, int, str, bool, Optional[str]]]):
        """Batch log multiple file operations for better performance."""
        async with await self._pool.acquire() as conn:
            await conn.executemany(
                self._prepared_statements['insert_operation'],
                operations
            )
            await conn.commit()

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._stats_cache.clear()
