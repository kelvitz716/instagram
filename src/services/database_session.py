"""Database service with session storage support."""
import logging
import sqlite3
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
from .session_storage import SessionStorageService

logger = logging.getLogger(__name__)

class DatabaseService:
    """Handles all database operations including session storage."""
    
    async def _create_tables(self, conn: sqlite3.Connection):
        """Create all required database tables."""
        try:
            # Load and execute the session storage migration
            migration_path = Path(__file__).parent.parent.parent / 'migrations' / '001_session_storage.sql'
            with open(migration_path, 'r') as f:
                conn.executescript(f.read())
                
            # Prepare session-related statements
            await self._prepare_session_statements(conn)
                
        except sqlite3.Error as e:
            logger.error(f"Failed to create tables: {e}")
            raise
    
    async def _prepare_session_statements(self, conn: sqlite3.Connection):
        """Prepare SQL statements for session management."""
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
    
    # Session management methods
    
    async def store_instagram_session(self, user_id: int, username: str, 
                                    session_type: str, session_data: str,
                                    cookies_file_path: Optional[str] = None,
                                    make_active: bool = True,
                                    expires_at: Optional[datetime] = None) -> int:
        """Store a new Instagram session."""
        async with self.connection() as conn:
            if make_active:
                # Deactivate other sessions for this user
                await conn.execute(
                    "UPDATE instagram_sessions SET is_active = 0 WHERE user_id = ?",
                    (user_id,)
                )
            
            cursor = await conn.execute(
                self._prepared_statements['insert_session'],
                (user_id, username, session_type, cookies_file_path, 
                 session_data, make_active, expires_at)
            )
            return cursor.lastrowid
    
    async def get_active_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the active session for a user."""
        async with self.connection() as conn:
            cursor = await conn.execute(
                self._prepared_statements['get_active_session'],
                (user_id,)
            )
            row = await cursor.fetchone()
            if row:
                return {
                    'id': row[0],
                    'session_type': row[1],
                    'cookies_file_path': row[2],
                    'session_data': row[3],
                    'last_validated': row[4]
                }
            return None
    
    async def get_all_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        async with self.connection() as conn:
            cursor = await conn.execute(
                self._prepared_statements['get_all_sessions'],
                (user_id,)
            )
            rows = await cursor.fetchall()
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
    
    async def update_session(self, session_id: int, session_data: str,
                           is_active: bool, expires_at: Optional[datetime] = None) -> bool:
        """Update an existing session."""
        async with self.connection() as conn:
            cursor = await conn.execute(
                self._prepared_statements['update_session'],
                (session_data, is_active, expires_at, session_id)
            )
            return cursor.rowcount > 0
    
    async def delete_session(self, session_id: int) -> bool:
        """Delete a session."""
        async with self.connection() as conn:
            cursor = await conn.execute(
                self._prepared_statements['delete_session'],
                (session_id,)
            )
            return cursor.rowcount > 0
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions. Returns number of deleted sessions."""
        async with self.connection() as conn:
            cursor = await conn.execute(
                self._prepared_statements['cleanup_expired_sessions']
            )
            return cursor.rowcount
    
    async def log_session_validation(self, session_id: int, 
                                   is_valid: bool, 
                                   error_message: Optional[str] = None):
        """Log a session validation attempt."""
        async with self.connection() as conn:
            await conn.execute(
                self._prepared_statements['insert_validation'],
                (session_id, is_valid, error_message)
            )