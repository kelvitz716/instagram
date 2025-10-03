"""Telegram session storage service that mirrors Instagram session management."""

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from telethon import TelegramClient
from ..services.database import DatabaseService

logger = logging.getLogger(__name__)

class TelegramSessionStorageError(Exception):
    """Exception raised for Telegram session storage errors."""
    pass

class TelegramSessionStorage:
    """Manages storage and retrieval of Telegram bot sessions using the same pattern as Instagram sessions."""

    def __init__(self, db_service: DatabaseService, sessions_path: Path, phone_number: Optional[str] = None):
        """Initialize the Telegram session storage service.
        
        Args:
            db_service: DatabaseService instance
            sessions_path: Path where session files will be stored
            phone_number: Optional phone number for automated authentication
        """
        self.db = db_service
        self.sessions_path = sessions_path
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        self.phone_number = phone_number
        
        # Bot-specific session info (since this is for the bot itself, not users)
        self.bot_session_name = "telegram_bot_session"

    async def store_telegram_session(self, session_file_path: Path, 
                                   phone_number: str, user_info: Dict[str, Any], 
                                   make_active: bool = True) -> int:
        """Store a Telegram session in the database and file system.
        
        Args:
            session_file_path: Path to the .session file created by Telethon
            phone_number: Phone number used for authentication
            user_info: Information about the authenticated user
            make_active: Whether to mark this session as active (default: True)
            
        Returns:
            int: Session record ID
        """
        try:
            if not session_file_path.exists():
                raise TelegramSessionStorageError(f"Session file not found: {session_file_path}")

            # Store the session file in our managed location
            stored_path = self._store_session_file(session_file_path)
            
            # Prepare session metadata
            session_data = {
                "phone_number": phone_number,
                "user_info": user_info,
                "created_at": datetime.now().isoformat(),
                "last_used": datetime.now().isoformat()
            }
            
            # Store in database using existing method pattern
            session_id = await self.db.store_telegram_session(
                session_name=self.bot_session_name,
                session_file_path=str(stored_path),
                session_data=json.dumps(session_data),
                phone_number=phone_number,
                is_active=True,
                expires_at=datetime.now() + timedelta(days=365)  # Telegram sessions last longer
            )
            
            logger.info(f"Stored Telegram session with ID {session_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"Failed to store Telegram session: {e}")
            raise TelegramSessionStorageError(f"Failed to store session: {str(e)}")

    def _store_session_file(self, source_path: Path) -> Path:
        """Store a session file in the managed sessions directory."""
        try:
            if not source_path.exists():
                raise TelegramSessionStorageError(f"Source session file not found: {source_path}")
            
            # Create final path in sessions directory
            stored_session_path = self.sessions_path / f"{self.bot_session_name}.session"
                
            # Create backup of existing session if it exists
            if stored_session_path.exists():
                backup_path = stored_session_path.with_suffix('.session.backup')
                shutil.copy2(stored_session_path, backup_path)
                logger.info(f"Backed up existing session to {backup_path}")
            
            # Copy new session file
            shutil.copy2(source_path, stored_session_path)
            logger.info(f"Stored session file at {stored_session_path}")
            
            return stored_session_path
            
        except Exception as e:
            logger.error(f"Failed to store session file: {e}")
            raise TelegramSessionStorageError(f"Failed to store session file: {str(e)}")

    async def get_active_session(self) -> Optional[Dict[str, Any]]:
        """Get the active Telegram session for the bot."""
        try:
            session = await self.db.get_active_telegram_session()
            if session:
                # Parse session data
                try:
                    session['session_data'] = json.loads(session['session_data'])
                except json.JSONDecodeError:
                    session['session_data'] = {}
                
                # Verify session file still exists
                session_file_path = Path(session['session_file_path'])
                if not session_file_path.exists():
                    logger.warning(f"Session file not found: {session_file_path}")
                    return None
                    
            return session
            
        except Exception as e:
            logger.error(f"Failed to get active Telegram session: {e}")
            return None

    async def update_session_usage(self, session_id: int) -> bool:
        """Update the last_used timestamp for a session."""
        try:
            # Get current session data
            session = await self.get_active_session()
            if not session or session['id'] != session_id:
                return False
                
            # Update last_used timestamp
            session_data = session['session_data']
            session_data['last_used'] = datetime.now().isoformat()
            
            # Update in database
            return await self.db.update_telegram_session(
                session_id,
                session_data=json.dumps(session_data)
            )
            
        except Exception as e:
            logger.error(f"Failed to update session usage: {e}")
            return False

    async def validate_stored_session(self, api_id: int, api_hash: str) -> bool:
        """Validate that the stored session is still valid."""
        try:
            session = await self.get_active_session()
            if not session:
                return False
                
            session_file_path = Path(session['session_file_path'])
            if not session_file_path.exists():
                return False
            
            # Try to create a client with the stored session
            session_name = str(session_file_path).replace('.session', '')
            client = TelegramClient(
                session_name,
                api_id,
                api_hash
            )
            
            try:
                await client.start()
                me = await client.get_me()
                if me:
                    logger.info(f"Session validation successful for {me.phone}")
                    await self.update_session_usage(session['id'])
                    return True
                    
            except Exception as e:
                logger.warning(f"Session validation failed: {e}")
                return False
            finally:
                await client.disconnect()
                
        except Exception as e:
            logger.error(f"Error validating session: {e}")
            return False

    def get_session_file_path(self) -> Path:
        """Get the path where the session file should be stored."""
        return self.sessions_path / f"{self.bot_session_name}.session"

    async def cleanup_old_sessions(self) -> int:
        """Clean up old/expired Telegram sessions."""
        try:
            # Remove expired sessions from database
            deleted_count = await self.db.cleanup_expired_telegram_sessions()
            
            # Clean up backup files older than 30 days
            cutoff_date = datetime.now() - timedelta(days=30)
            cleaned_files = 0
            
            for backup_file in self.sessions_path.glob("*.backup"):
                try:
                    file_time = datetime.fromtimestamp(backup_file.stat().st_mtime)
                    if file_time < cutoff_date:
                        backup_file.unlink()
                        cleaned_files += 1
                        logger.info(f"Removed old backup: {backup_file}")
                except Exception as e:
                    logger.warning(f"Failed to clean backup file {backup_file}: {e}")
            
            if deleted_count > 0 or cleaned_files > 0:
                logger.info(f"Cleaned up {deleted_count} database records and {cleaned_files} backup files")
                
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup sessions: {e}")
            return 0