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

    def __init__(self, db_service: DatabaseService, downloads_path: Path):
        """Initialize the Telegram session storage service.
        
        Args:
            db_service: DatabaseService instance
            downloads_path: Base downloads path (sessions will be stored at downloads_path/sessions)
        """
        self.db = db_service
        # Store sessions in downloads/sessions for consistency with the database path
        self.sessions_path = downloads_path / "sessions" 
        self.sessions_path.mkdir(parents=True, exist_ok=True)
        
        # Bot-specific session info (since this is for the bot itself, not users)
        self.bot_session_name = "telegram_bot_session"
        
        logger.info(f"Telegram session storage initialized. Sessions path: {self.sessions_path}")

    async def store_telegram_session(self, session_file_path: Path, 
                                   phone_number: str, user_info: Dict[str, Any]) -> int:
        """Store a Telegram session in the database and file system.
        
        Args:
            session_file_path: Path to the .session file created by Telethon
            phone_number: Phone number used for authentication
            user_info: Information about the authenticated user
            
        Returns:
            int: Session record ID
        """
        try:
            if not session_file_path.exists():
                raise TelegramSessionStorageError(f"Session file not found: {session_file_path}")

            logger.info(f"Storing Telegram session from: {session_file_path}")
            
            # Store the session file in our managed location
            stored_path = self._store_session_file(session_file_path)
            
            # Prepare session metadata
            session_data = {
                "phone_number": phone_number,
                "user_info": user_info,
                "created_at": datetime.now().isoformat(),
                "last_used": datetime.now().isoformat(),
                "stored_path": str(stored_path)  # Include actual storage path
            }
            
            # Store in database with the correct path
            session_id = await self.db.store_telegram_session(
                session_name=self.bot_session_name,
                session_file_path=str(stored_path),  # Use the stored path, not original
                session_data=json.dumps(session_data),
                phone_number=phone_number,
                is_active=True,
                expires_at=datetime.now() + timedelta(days=365)  # Telegram sessions last longer
            )
            
            logger.info(f"Stored Telegram session with ID {session_id} at {stored_path}")
            
            # Verify the file was actually stored
            if not stored_path.exists():
                raise TelegramSessionStorageError(f"Session file was not properly stored at {stored_path}")
            
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
            
            logger.info(f"Copying session from {source_path} to {stored_session_path}")
                
            # Create backup of existing session if it exists
            if stored_session_path.exists():
                backup_path = stored_session_path.with_suffix('.session.backup')
                shutil.copy2(stored_session_path, backup_path)
                logger.info(f"Backed up existing session to {backup_path}")
            
            # Ensure the sessions directory exists
            stored_session_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy new session file
            shutil.copy2(source_path, stored_session_path)
            
            # Set proper permissions
            stored_session_path.chmod(0o644)
            
            logger.info(f"Session file stored successfully at {stored_session_path}")
            logger.info(f"Session file size: {stored_session_path.stat().st_size} bytes")
            
            return stored_session_path
            
        except Exception as e:
            logger.error(f"Failed to store session file: {e}")
            raise TelegramSessionStorageError(f"Failed to store session file: {str(e)}")

    async def get_active_session(self) -> Optional[Dict[str, Any]]:
        """Get the active Telegram session for the bot."""
        try:
            logger.debug("Retrieving active Telegram session from database")
            session = await self.db.get_active_telegram_session()
            
            if not session:
                logger.info("No active Telegram session found in database")
                return None
            
            logger.info(f"Found active session with ID {session['id']}")
            
            # Parse session data
            try:
                session['session_data'] = json.loads(session['session_data'])
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse session data: {e}")
                session['session_data'] = {}
            
            # Verify session file still exists
            session_file_path = Path(session['session_file_path'])
            logger.info(f"Checking session file at: {session_file_path}")
            
            if not session_file_path.exists():
                logger.warning(f"Session file not found at: {session_file_path}")
                
                # Try to find it in alternate locations
                alternate_paths = [
                    self.sessions_path / f"{self.bot_session_name}.session",
                    Path("sessions") / f"{self.bot_session_name}.session",
                    Path(f"{self.bot_session_name}.session")
                ]
                
                found_path = None
                for alt_path in alternate_paths:
                    if alt_path.exists():
                        logger.info(f"Found session file at alternate location: {alt_path}")
                        found_path = alt_path
                        break
                
                if found_path:
                    # Update the database with the correct path
                    await self.db.update_telegram_session(
                        session['id'],
                        session_file_path=str(found_path)
                    )
                    session['session_file_path'] = str(found_path)
                else:
                    logger.error("Session file not found in any expected location")
                    return None
            else:
                logger.info(f"Session file found, size: {session_file_path.stat().st_size} bytes")
                
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
                logger.info("No active session to validate")
                return False
                
            session_file_path = Path(session['session_file_path'])
            if not session_file_path.exists():
                logger.error(f"Session file not found for validation: {session_file_path}")
                return False
            
            logger.info(f"Validating session file: {session_file_path}")
            
            # Try to create a client with the stored session
            # Remove .session extension for Telethon
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
                else:
                    logger.warning("Session validation failed: unable to get user info")
                    return False
                    
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
    def debug_session_files(self):
        """Debug helper to show session file locations."""
        logger.info("=== Session File Debug Info ===")
        logger.info(f"Sessions directory: {self.sessions_path}")
        logger.info(f"Expected session file: {self.get_session_file_path()}")
        
        # List all files in sessions directory
        if self.sessions_path.exists():
            files = list(self.sessions_path.iterdir())
            logger.info(f"Files in sessions directory: {[f.name for f in files]}")
            
            for file in files:
                if file.is_file():
                    logger.info(f"  {file.name}: {file.stat().st_size} bytes")
        else:
            logger.warning(f"Sessions directory does not exist: {self.sessions_path}")
            
        # Check alternate locations
        alternate_paths = [
            Path("sessions") / f"{self.bot_session_name}.session",
            Path(f"{self.bot_session_name}.session")
        ]
        
        for alt_path in alternate_paths:
            if alt_path.exists():
                logger.info(f"Found session file at alternate location: {alt_path} ({alt_path.stat().st_size} bytes)")
