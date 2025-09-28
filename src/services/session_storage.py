"""Session storage service for managing Instagram sessions."""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from ..core.config import DatabaseConfig

logger = logging.getLogger(__name__)

class SessionStorageError(Exception):
    """Exception raised for session storage errors."""
    pass

class SessionStorageService:
    """Manages storage and retrieval of Instagram sessions."""

    def __init__(self, db_service, downloads_path: Path):
        """Initialize the session storage service.
        
        Args:
            db_service: DatabaseService instance
            downloads_path: Path where cookie files will be stored
        """
        self.db = db_service
        self.sessions_path = downloads_path / "sessions"
        self.sessions_path.mkdir(parents=True, exist_ok=True)

    async def store_session(self, user_id: int, username: str,
                          session_type: str, session_data: Dict[str, str],
                          cookies_file_path: Optional[Path] = None,
                          make_active: bool = True) -> int:
        """Store a new Instagram session.
        
        Args:
            user_id: Telegram user ID
            username: Instagram username
            session_type: Either 'firefox' or 'cookies_file'
            session_data: Cookie data dictionary
            cookies_file_path: Path to cookies.txt file (if applicable)
            make_active: Whether to make this the active session
            
        Returns:
            int: Session ID
        """
        try:
            # Calculate expiration (30 days from now by default)
            expires_at = datetime.now() + timedelta(days=30)
            
            # Store cookie file if provided
            if cookies_file_path and session_type == 'cookies_file':
                stored_path = self._store_cookie_file(user_id, cookies_file_path)
                cookies_file_path = str(stored_path)
            
            # Store session in database
            cookies_file_path_str = str(cookies_file_path) if cookies_file_path else None
            session_id = await self.db.store_instagram_session(
                user_id=user_id,
                username=username,
                session_type=session_type,
                session_data=json.dumps(session_data),
                cookies_file_path=cookies_file_path_str,
                make_active=make_active,
                expires_at=expires_at
            )
            
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to store session: {e}")
            raise SessionStorageError(f"Failed to store session: {str(e)}")
    
    def _store_cookie_file(self, user_id: int, source_path: Path) -> Path:
        """Store a cookie file in the sessions directory with enhanced error handling."""
        try:
            # Validate source file
            if not source_path.exists():
                raise SessionStorageError(f"Source cookie file not found: {source_path}")
                
            if source_path.stat().st_size == 0:
                raise SessionStorageError("Cookie file is empty")
                
            # Create user-specific directory
            user_path = self.sessions_path / str(user_id)
            user_path.mkdir(parents=True, exist_ok=True)
            
            # Create final path
            dest_path = user_path / "cookies.txt"
            temp_path = user_path / f"temp_cookies_{int(datetime.now().timestamp())}.txt"
            
            try:
                # First copy to temp file
                with open(source_path, 'r', encoding='utf-8') as src, \
                     open(temp_path, 'w', encoding='utf-8') as dst:
                    content = src.read()
                    if not any(domain in content for domain in ['.instagram.com', 'instagram.com']):
                        raise SessionStorageError("No Instagram cookies found in file")
                    dst.write(content)
                
                # If copy successful, move to final location
                if dest_path.exists():
                    dest_path.unlink()
                temp_path.rename(dest_path)
                logger.info(f"Successfully stored cookie file for user {user_id}")
                
                return dest_path
                
            finally:
                # Clean up temp file if it exists
                if temp_path.exists():
                    temp_path.unlink()
            
        except Exception as e:
            logger.error(f"Failed to store cookie file: {e}")
            # Clean up destination file if it exists after error
            if 'dest_path' in locals() and dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            raise SessionStorageError(f"Failed to store cookie file: {str(e)}")
    
    async def get_active_session(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the active session for a user."""
        try:
            session = await self.db.get_active_session(user_id)
            if session:
                try:
                    session['session_data'] = json.loads(session['session_data'])
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode session data: {e}")
                    session['session_data'] = {}
            return session
        except Exception as e:
            logger.error(f"Failed to get active session: {e}")
            raise SessionStorageError(f"Failed to get active session: {str(e)}")
    
    async def get_all_sessions(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all sessions for a user."""
        try:
            sessions = await self.db.get_all_sessions(user_id)
            for session in sessions:
                try:
                    if isinstance(session['session_data'], str):
                        session['session_data'] = json.loads(session['session_data'])
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Failed to decode session data: {e}")
                    session['session_data'] = {}
            return sessions
        except Exception as e:
            logger.error(f"Failed to get sessions: {e}")
            raise SessionStorageError(f"Failed to get sessions: {str(e)}")
    
    async def set_active_session(self, user_id: int, session_id: int) -> bool:
        """Set a session as active and deactivate others."""
        try:
            # Get the session to make sure it exists and belongs to the user
            sessions = await self.get_all_sessions(user_id)
            target_session = next((s for s in sessions if s['id'] == session_id), None)
            
            if not target_session:
                raise SessionStorageError("Session not found or doesn't belong to user")
            
            # Deactivate all other sessions
            for session in sessions:
                if session['id'] != session_id:
                    await self.db.update_session(
                        session['id'],
                        session_data=json.dumps(session['session_data']),
                        is_active=False
                    )
            
            # Activate target session
            return await self.db.update_session(
                session_id,
                session_data=json.dumps(target_session['session_data']),
                is_active=True
            )
            
        except Exception as e:
            logger.error(f"Failed to set active session: {e}")
            raise SessionStorageError(f"Failed to set active session: {str(e)}")
    
    async def delete_session(self, user_id: int, session_id: int) -> bool:
        """Delete a session and its associated files."""
        try:
            # Get session to check ownership and get file path
            sessions = await self.get_all_sessions(user_id)
            session = next((s for s in sessions if s['id'] == session_id), None)
            
            if not session:
                raise SessionStorageError("Session not found or doesn't belong to user")
            
            # Delete cookie file if it exists
            if session['cookies_file_path']:
                try:
                    cookie_file = Path(session['cookies_file_path'])
                    if cookie_file.exists():
                        cookie_file.unlink()
                        logger.info(f"Deleted cookie file for session {session_id}")
                    user_dir = cookie_file.parent
                    if user_dir.exists() and not any(user_dir.iterdir()):
                        user_dir.rmdir()
                        logger.info(f"Removed empty user directory: {user_dir}")
                except Exception as e:
                    logger.warning(f"Failed to delete cookie file: {e}")
            
            # Delete from database
            success = await self.db.delete_session(session_id)
            if success:
                logger.info(f"Successfully deleted session {session_id} for user {user_id}")
            return success
            
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            raise SessionStorageError(f"Failed to delete session: {str(e)}")
    
    async def cleanup_expired_sessions(self) -> int:
        """Clean up expired sessions and their files."""
        try:
            # Get all sessions before cleanup to handle files
            all_sessions = []
            for user_path in self.sessions_path.iterdir():
                if user_path.is_dir():
                    try:
                        user_id = int(user_path.name)
                        sessions = await self.get_all_sessions(user_id)
                        all_sessions.extend(sessions)
                    except ValueError:
                        continue
            
            # Delete expired sessions from database
            deleted_count = await self.db.cleanup_expired_sessions()
            
            # Clean up orphaned cookie files
            self._cleanup_orphaned_files(all_sessions)
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup sessions: {e}")
            raise SessionStorageError(f"Failed to cleanup sessions: {str(e)}")
    
    def _cleanup_orphaned_files(self, active_sessions: List[Dict[str, Any]]):
        """Clean up cookie files that don't belong to any active session."""
        try:
            # Get all cookie file paths from active sessions
            active_paths = {
                Path(s['cookies_file_path'])
                for s in active_sessions
                if s['cookies_file_path']
            }
            
            # Check each user's session directory
            for user_path in self.sessions_path.iterdir():
                if not user_path.is_dir():
                    continue
                    
                # Delete orphaned cookie files
                for file_path in user_path.glob("cookies_*.txt"):
                    if file_path not in active_paths:
                        try:
                            file_path.unlink()
                            logger.info(f"Deleted orphaned cookie file: {file_path}")
                        except Exception as e:
                            logger.warning(f"Failed to delete orphaned file {file_path}: {e}")
                
                # Remove empty user directories
                if not any(user_path.iterdir()):
                    try:
                        user_path.rmdir()
                        logger.info(f"Removed empty session directory: {user_path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove empty directory {user_path}: {e}")
                        
        except Exception as e:
            logger.error(f"Error cleaning up orphaned files: {e}")