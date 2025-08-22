from pathlib import Path
from typing import Optional, Dict, List, Union
import logging
import mimetypes
import httpx
from ..core.retry import RetryableOperation
from .upload import UploaderBase, UploadResult

logger = logging.getLogger(__name__)

class BotAPIUploader(UploaderBase):
    """Handles file uploads through Telegram Bot API"""
    
    def __init__(self, bot_token: str, chat_id: Union[int, str], proxy: Optional[str] = None):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.proxy = proxy
        self.api_url = f"https://api.telegram.org/bot{bot_token}"
        self.max_file_size = 50 * 1024 * 1024  # 50MB Telegram limit
        self._setup_mime_types()
        
    def _setup_mime_types(self):
        """Ensure all common mime types are registered"""
        mimetypes.init()
        # Add common video formats if not registered
        if not mimetypes.guess_type("test.mp4")[0]:
            mimetypes.add_type("video/mp4", ".mp4")
        if not mimetypes.guess_type("test.mkv")[0]:
            mimetypes.add_type("video/x-matroska", ".mkv")
    
    def can_handle(self, file_path: Path) -> bool:
        """Check if file can be handled (size within limits)"""
        try:
            return file_path.stat().st_size <= self.max_file_size
        except OSError:
            return False
    
    @RetryableOperation()
    async def upload(self, file_path: Path, caption: Optional[str] = None) -> bool:
        """
        Upload file to Telegram using Bot API
        
        Args:
            file_path: Path to the file to upload
            caption: Optional caption for the media
            
        Returns:
            bool: True if upload was successful
        """
        mime_type = mimetypes.guess_type(file_path)[0]
        if not mime_type:
            logger.warning(f"Could not determine mime type for {file_path}")
            mime_type = "application/octet-stream"
            
        # Determine the appropriate API method based on mime type
        method = self._get_upload_method(mime_type)
        if not method:
            logger.error(f"Unsupported mime type: {mime_type}")
            return False
            
        try:
            # Set up client with proxy if configured
            client_kwargs = {}
            if self.proxy:
                client_kwargs['proxies'] = {
                    'http://': self.proxy,
                    'https://': self.proxy
                }
            async with httpx.AsyncClient(**client_kwargs) as client:
                with open(file_path, "rb") as file:
                    files = {
                        method.replace("send", "").lower(): (
                            file_path.name, 
                            file, 
                            mime_type
                        )
                    }
                    data = {"chat_id": self.chat_id}
                    if caption:
                        data["caption"] = caption
                        
                    response = await client.post(
                        f"{self.api_url}/{method}",
                        files=files,
                        data=data
                    )
                    
                    if response.status_code == 200:
                        return True
                    else:
                        logger.error(
                            f"Upload failed with status {response.status_code}: {response.text}"
                        )
                        return False
                        
        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return False
            
    def _get_upload_method(self, mime_type: str) -> Optional[str]:
        """Determine the appropriate Telegram API method based on mime type"""
        if mime_type.startswith("image/"):
            return "sendPhoto"
        elif mime_type.startswith("video/"):
            return "sendVideo"
        elif mime_type.startswith("audio/"):
            return "sendAudio"
        elif mime_type.startswith("text/"):
            return "sendDocument"
        # Default to document for other types
        return "sendDocument"
    
    async def upload_chunk(self, chunk: bytes, chunk_index: int, total_chunks: int) -> bool:
        """Telegram Bot API doesn't support chunked uploads, so we'll return False"""
        return False

    async def finalize_upload(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Telegram Bot API doesn't support chunked uploads, so we'll return a failed result"""
        return UploadResult(False, error="Chunked uploads not supported by Bot API")

    async def upload_small_file(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Upload a small file directly through Bot API"""
        try:
            # Check file size
            file_size = file_path.stat().st_size
            if file_size > self.max_file_size:
                return UploadResult(False, error=f"File too large for Bot API ({file_size} > {self.max_file_size})")

            mime_type = self.get_mime_type(file_path)
            method = self._get_upload_method(mime_type)
            if not method:
                return UploadResult(False, error=f"Unsupported mime type: {mime_type}")

            # Set up client with proxy if configured
            client_kwargs = {}
            if self.proxy:
                client_kwargs['proxies'] = {
                    'http://': self.proxy,
                    'https://': self.proxy
                }

            async with httpx.AsyncClient(**client_kwargs) as client:
                with open(file_path, "rb") as file:
                    files = {
                        method.replace("send", "").lower(): (
                            file_path.name, 
                            file, 
                            mime_type
                        )
                    }
                    data = {"chat_id": self.chat_id}
                    if caption:
                        data["caption"] = caption

                    response = await client.post(
                        f"{self.api_url}/{method}",
                        files=files,
                        data=data
                    )

                    if response.status_code == 200:
                        response_data = response.json()
                        if response_data.get('ok'):
                            result = response_data.get('result', {})
                            message_id = result.get('message_id')
                            return UploadResult(True, message_id=message_id, file_size=file_size)
                        else:
                            error = response_data.get('description', 'Unknown error')
                            return UploadResult(False, error=error)
                    else:
                        return UploadResult(False, error=f"Upload failed with status {response.status_code}: {response.text}")

        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return UploadResult(False, error=str(e))
