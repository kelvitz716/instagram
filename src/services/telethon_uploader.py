from pathlib import Path
from typing import Optional, Union
import logging
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerUser
from ..core.retry import RetryableOperation
from .upload import UploaderBase

logger = logging.getLogger(__name__)

class TelethonUploader(UploaderBase):
    """Handles file uploads through Telethon client"""
    
    def __init__(
        self, 
        client: TelegramClient,
        chat_id: Union[int, str],
        api_id: int,
        api_hash: str
    ):
        self.client = client
        self.chat_id = chat_id
        self.api_id = api_id
        self.api_hash = api_hash
        
    async def _ensure_client_connected(self):
        """Ensure the Telethon client is connected"""
        if not self.client.is_connected():
            await self.client.connect()
            
        if not await self.client.is_user_authorized():
            logger.error("Telethon client is not authorized")
            raise RuntimeError("Telethon client is not authorized")
    
    def can_handle(self, file_path: Path) -> bool:
        """Telethon can handle files of any size"""
        return True
    
    @RetryableOperation()
    async def upload(self, file_path: Path, caption: Optional[str] = None) -> bool:
        """
        Upload file using Telethon client
        
        Args:
            file_path: Path to the file to upload
            caption: Optional caption for the media
            
        Returns:
            bool: True if upload was successful
        """
        try:
            await self._ensure_client_connected()
            
            # Get the peer entity
            try:
                entity = await self.client.get_entity(self.chat_id)
            except ValueError as e:
                logger.error(f"Could not find entity for chat_id {self.chat_id}: {e}")
                return False
            
            # Upload the file
            try:
                await self.client.send_file(
                    entity,
                    file_path,
                    caption=caption,
                    progress_callback=self._upload_progress
                )
                return True
            except Exception as e:
                logger.error(f"Failed to upload file: {e}", exc_info=True)
                return False
                
        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return False
            
    async def _upload_progress(self, current, total):
        """Callback for upload progress"""
        if total:
            percentage = (current / total) * 100
            logger.debug(f"Upload progress: {percentage:.1f}%")
