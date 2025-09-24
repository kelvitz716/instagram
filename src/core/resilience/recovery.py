"""Session and state recovery mechanisms."""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

import structlog
from telegram import Message, error as telegram_error

from src.core.resilience.retry import with_retry
from src.core.resilience.circuit_breaker import with_circuit_breaker

logger = structlog.get_logger(__name__)

class SessionRecovery:
    """Handles recovery of Instagram and Telegram sessions."""
    
    def __init__(self, services):
        self.services = services
        self._recovery_in_progress = False
        
    @with_retry(
        max_retries=3,
        exceptions=[ConnectionError, TimeoutError]
    )
    async def recover_instagram_session(self) -> bool:
        """
        Attempt to recover Instagram session.
        
        Returns:
            bool: True if recovery was successful
        """
        if self._recovery_in_progress:
            logger.info("Instagram session recovery already in progress")
            return False
            
        try:
            self._recovery_in_progress = True
            logger.info("Attempting Instagram session recovery")
            
            # First try refreshing the session
            try:
                await self.services.instagram_service.refresh_session()
                logger.info("Instagram session refreshed successfully")
                return True
                
            except Exception as e:
                logger.warning(
                    "Session refresh failed, attempting relogin",
                    error=str(e)
                )
                
            # If refresh fails, try complete relogin
            await asyncio.sleep(60)  # Wait before retry
            await self.services.instagram_service.login()
            logger.info("Instagram session restored through relogin")
            return True
            
        except Exception as e:
            logger.error("Instagram session recovery failed", error=str(e))
            return False
            
        finally:
            self._recovery_in_progress = False
            
    async def recover_telegram_session(self) -> bool:
        """
        Attempt to recover Telegram session.
        
        Returns:
            bool: True if recovery was successful
        """
        try:
            if not self.services.telegram_client.is_connected():
                await self.services.telegram_client.connect()
                logger.info("Telegram session reconnected")
            return True
            
        except Exception as e:
            logger.error("Telegram session recovery failed", error=str(e))
            return False
            
class StateRecovery:
    """Handles recovery of download and upload states."""
    
    def __init__(self, services):
        self.services = services
        
    async def save_download_state(
        self,
        url: str,
        downloaded_files: List[Path],
        status_message: Optional[Message] = None
    ) -> None:
        """Save download state for potential recovery."""
        state = {
            'url': url,
            'files': [str(f) for f in downloaded_files],
            'timestamp': datetime.now().isoformat(),
            'status_message_id': status_message.message_id if status_message else None,
            'chat_id': status_message.chat_id if status_message else None
        }
        
        await self.services.database_service.save_download_state(state)
        
    async def get_pending_downloads(self) -> List[Dict[str, Any]]:
        """Get list of downloads that need recovery."""
        return await self.services.database_service.get_pending_downloads()
        
    @with_retry(exceptions=[telegram_error.RetryAfter])
    async def resume_download(self, state: Dict[str, Any]) -> bool:
        """
        Resume an interrupted download.
        
        Args:
            state: The saved download state
            
        Returns:
            bool: True if resume was successful
        """
        try:
            # Verify files aren't already downloaded
            files = [Path(f) for f in state['files']]
            missing_files = [f for f in files if not f.exists()]
            
            if not missing_files:
                logger.info("All files already downloaded", url=state['url'])
                return True
                
            # Resume download
            await self.services.instagram_service.download_post(
                url=state['url'],
                status_message=None  # Create new status message
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to resume download",
                url=state['url'],
                error=str(e)
            )
            return False
