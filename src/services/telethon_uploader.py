from pathlib import Path
from typing import Optional, Union
import logging
import asyncio
from telethon import TelegramClient
from telethon.tl.types import InputPeerChannel, InputPeerUser, MessageMediaDocument
from ..core.retry import RetryableOperation
from .upload import UploaderBase, UploadResult

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
        super().__init__()
        self.client = client
        self.chat_id = chat_id
        self.api_id = api_id
        self.api_hash = api_hash
        self._current_upload = None
        self._upload_parts = []
        
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
    
    async def upload_chunk(self, chunk: bytes, chunk_index: int, total_chunks: int) -> bool:
        """Upload a single chunk through Telethon"""
        try:
            if not self._current_upload:
                # Start a new upload if this is the first chunk
                self._current_upload = await self.client.upload_file(bytes([]))
                self._upload_parts = []

            # Add chunk to the parts list
            self._upload_parts.append(chunk)
            return True
        except Exception as e:
            logger.error(f"Chunk upload failed: {e}", exc_info=True)
            return False

    async def finalize_upload(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Finalize the chunked upload by combining all chunks and sending the file"""
        if not self._current_upload or not self._upload_parts:
            return UploadResult(False, error="No upload in progress")

        try:
            await self._ensure_client_connected()

            # Combine all chunks
            full_data = b''.join(self._upload_parts)
            file_handle = await self.client.upload_file(full_data, file_name=file_path.name)

            # Get the peer entity
            try:
                entity = await self.client.get_entity(self.chat_id)
            except ValueError as e:
                return UploadResult(False, error=f"Could not find entity for chat_id {self.chat_id}: {e}")

            # Send the file
            message = await self.client.send_file(
                entity,
                file_handle,
                caption=caption,
                progress_callback=self._upload_progress
            )

            # Get message ID if the upload was successful
            if isinstance(message.media, MessageMediaDocument):
                return UploadResult(True, message_id=message.id, file_size=len(full_data))
            else:
                return UploadResult(False, error="Upload completed but no document was created")

        except Exception as e:
            logger.error(f"Upload finalization failed: {e}", exc_info=True)
            return UploadResult(False, error=str(e))
        finally:
            # Clear the upload state
            self._current_upload = None
            self._upload_parts = []

    async def upload_small_file(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Upload a small file directly through Telethon"""
        try:
            await self._ensure_client_connected()

            # Get the peer entity
            try:
                entity = await self.client.get_entity(self.chat_id)
            except ValueError as e:
                return UploadResult(False, error=f"Could not find entity for chat_id {self.chat_id}: {e}")

            # Send the file
            message = await self.client.send_file(
                entity,
                file_path,
                caption=caption,
                progress_callback=self._upload_progress
            )

            # Get message ID and file size if the upload was successful
            if isinstance(message.media, MessageMediaDocument):
                return UploadResult(True, message_id=message.id, file_size=file_path.stat().st_size)
            else:
                return UploadResult(False, error="Upload completed but no document was created")

        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return UploadResult(False, error=str(e))
