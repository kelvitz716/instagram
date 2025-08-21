from pathlib import Path
from typing import Optional, Dict, Type
from abc import ABC, abstractmethod
import logging
from ..core.config import UploadConfig
from ..core.retry import RetryableOperation

logger = logging.getLogger(__name__)

class UploaderBase(ABC):
    """Base class for file uploaders"""
    
    @abstractmethod
    async def upload(self, file_path: Path, caption: Optional[str] = None) -> bool:
        """Upload a file and return success status"""
        pass
    
    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Check if this uploader can handle the given file"""
        pass

class FileUploadService:
    """Handles all file upload operations"""
    
    def __init__(self, config: UploadConfig):
        self.config = config
        self.uploaders: Dict[str, UploaderBase] = {}
    
    def register_uploader(self, name: str, uploader: UploaderBase):
        """Register a new uploader"""
        self.uploaders[name] = uploader
    
    async def upload_file(
        self, 
        file_path: Path, 
        caption: Optional[str] = None,
        method: str = 'auto'
    ) -> bool:
        """
        Upload a file using the most appropriate uploader
        
        Args:
            file_path: Path to the file to upload
            caption: Optional caption for the media
            method: Upload method ('auto', 'bot_api', or 'telethon')
        
        Returns:
            bool: True if upload was successful
        """
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False
        
        uploader = self._select_uploader(file_path, method)
        if not uploader:
            logger.error(f"No suitable uploader found for {file_path}")
            return False
        
        try:
            return await uploader.upload(file_path, caption)
        except Exception as e:
            logger.error(f"Upload failed: {e}", exc_info=True)
            return False
    
    def _select_uploader(self, file_path: Path, method: str) -> Optional[UploaderBase]:
        """Select the most appropriate uploader for the file"""
        if method != 'auto':
            return self.uploaders.get(method)
        
        # Try each uploader in priority order
        for uploader in self.uploaders.values():
            if uploader.can_handle(file_path):
                return uploader
        
        return None
