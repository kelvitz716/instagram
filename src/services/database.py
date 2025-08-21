import aiosqlite
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
from ..core.config import DatabaseConfig

logger = logging.getLogger(__name__)

class DatabaseService:
    """Handles all database operations"""
    
    def __init__(self, config: DatabaseConfig):
        self.config = config
        self.db_path = Path(config.db_path)
        self._pool = None
        
    async def initialize(self):
        """Initialize the database and create tables if they don't exist"""
        async with aiosqlite.connect(self.db_path) as db:
            # Create downloads table
            await db.execute("""
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
            
            # Create uploads table
            await db.execute("""
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
            
            # Create file_operations table
            await db.execute("""
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
            
            await db.commit()
    
    async def record_download(
        self, 
        url: str, 
        status: str = "pending",
        file_paths: Optional[List[str]] = None,
        error: Optional[str] = None
    ) -> int:
        """Record a new download attempt"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO downloads (url, status, file_paths, error)
                VALUES (?, ?, ?, ?)
                """,
                (url, status, ','.join(file_paths) if file_paths else None, error)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def update_download(
        self,
        download_id: int,
        status: str,
        file_paths: Optional[List[str]] = None,
        error: Optional[str] = None
    ):
        """Update an existing download record"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE downloads 
                SET status = ?, file_paths = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, ','.join(file_paths) if file_paths else None, error, download_id)
            )
            await db.commit()
    
    async def record_upload(
        self,
        download_id: int,
        file_path: str,
        status: str = "pending",
        message_id: Optional[int] = None,
        error: Optional[str] = None
    ) -> int:
        """Record a new upload attempt"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO uploads (download_id, file_path, status, message_id, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (download_id, file_path, status, message_id, error)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def update_upload(
        self,
        upload_id: int,
        status: str,
        message_id: Optional[int] = None,
        error: Optional[str] = None
    ):
        """Update an existing upload record"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                UPDATE uploads 
                SET status = ?, message_id = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, message_id, error, upload_id)
            )
            await db.commit()
    
    async def get_pending_uploads(self) -> List[Dict[str, Any]]:
        """Get all pending uploads"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT * FROM uploads 
                WHERE status = 'pending'
                ORDER BY created_at ASC
                """
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def get_download_status(self, url: str) -> Optional[Dict[str, Any]]:
        """Get the status of a download by URL"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM downloads WHERE url = ? ORDER BY created_at DESC LIMIT 1",
                (url,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_statistics(self) -> Dict[str, Any]:
        """Get bot statistics from database"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            stats = {
                'total_downloads': 0,
                'successful_downloads': 0,
                'failed_downloads': 0,
                'total_uploads': 0,
                'successful_uploads': 0,
                'failed_uploads': 0
            }
            
            # Get download stats
            async with db.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM downloads
                """
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    stats['total_downloads'] = row[0]
                    stats['successful_downloads'] = row[1] or 0
                    stats['failed_downloads'] = row[2] or 0
                    
            # Get upload stats
            async with db.execute(
                """
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
                FROM uploads
                """
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    stats['total_uploads'] = row[0]
                    stats['successful_uploads'] = row[1] or 0
                    stats['failed_uploads'] = row[2] or 0
                    
            return stats

    async def log_file_operation(
        self,
        file_path: str,
        file_size: int,
        operation_type: str,
        success: bool,
        error: Optional[str] = None
    ) -> int:
        """Log a file operation (download/upload)"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO file_operations 
                (file_path, file_size, operation_type, success, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (file_path, file_size, operation_type, success, error)
            )
            await db.commit()
            return cursor.lastrowid

    async def close(self):
        """Close any open database connections"""
        if self._pool:
            await self._pool.close()
            self._pool = None
