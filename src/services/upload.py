import asyncio
from pathlib import Path
from typing import Optional, Dict, Type, Callable, AsyncGenerator
from abc import ABC, abstractmethod
import logging
import mimetypes
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from ..core.config import UploadConfig
from ..core.retry import RetryableOperation

logger = logging.getLogger(__name__)

# Constants for optimized chunk handling
CHUNK_SIZE = 1024 * 1024  # 1MB chunks for memory efficiency
MAX_CONCURRENT_CHUNKS = 4  # Maximum concurrent chunk uploads
UPLOAD_TIMEOUT = 300  # 5 minutes timeout for large files

@dataclass
class UploadResult:
    """Structured upload result"""
    success: bool
    message_id: Optional[int] = None
    error: Optional[str] = None
    file_size: int = 0
    duration_ms: int = 0

class UploaderBase(ABC):
    """Base class for file uploaders with optimized methods"""
    
    def __init__(self):
        self._chunk_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHUNKS)
        self._mime_types = self._initialize_mime_types()
    
    @staticmethod
    def _initialize_mime_types() -> Dict[str, str]:
        """Initialize mime type mapping with common types"""
        mime_map = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.mp4': 'video/mp4',
            '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo',
            '.webm': 'video/webm',
            '.mkv': 'video/x-matroska'
        }
        mimetypes.init()
        return mime_map
    
    @lru_cache(maxsize=100)
    def get_mime_type(self, file_path: Path) -> str:
        """Get mime type with caching"""
        ext = file_path.suffix.lower()
        return self._mime_types.get(ext) or mimetypes.guess_type(str(file_path))[0] or 'application/octet-stream'
    
    async def _read_chunks(self, file_path: Path) -> AsyncGenerator[bytes, None]:
        """Read file in chunks asynchronously"""
        async with await asyncio.to_thread(open, file_path, 'rb') as file:
            while chunk := await asyncio.to_thread(file.read, CHUNK_SIZE):
                yield chunk
    
    @abstractmethod
    async def upload_chunk(self, chunk: bytes, chunk_index: int, total_chunks: int) -> bool:
        """Upload a single chunk"""
        pass
    
    @abstractmethod
    async def finalize_upload(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Finalize the chunked upload"""
        pass
    
    async def upload(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Optimized file upload with chunking and progress tracking"""
        try:
            if not file_path.exists():
                return UploadResult(False, error="File not found")
            
            file_size = file_path.stat().st_size
            start_time = asyncio.get_event_loop().time()
            
            # For small files, use direct upload
            if file_size <= CHUNK_SIZE:
                result = await self.upload_small_file(file_path, caption)
            else:
                result = await self.upload_large_file(file_path, caption)
            
            duration_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
            result.duration_ms = duration_ms
            result.file_size = file_size
            
            return result
            
        except Exception as e:
            logger.error(f"Upload failed for {file_path}: {str(e)}", exc_info=True)
            return UploadResult(False, error=str(e))
    
    @abstractmethod
    async def upload_small_file(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Upload a small file directly"""
        pass
    
    async def upload_large_file(self, file_path: Path, caption: Optional[str] = None) -> UploadResult:
        """Upload a large file in chunks with concurrent processing"""
        chunks = []
        async for chunk in self._read_chunks(file_path):
            chunks.append(chunk)
        
        total_chunks = len(chunks)
        upload_tasks = []
        
        for i, chunk in enumerate(chunks):
            task = asyncio.create_task(self.upload_chunk(chunk, i, total_chunks))
            upload_tasks.append(task)
            
            # Limit concurrent chunks
            if len(upload_tasks) >= MAX_CONCURRENT_CHUNKS:
                await asyncio.gather(*upload_tasks)
                upload_tasks.clear()
        
        # Upload any remaining chunks
        if upload_tasks:
            await asyncio.gather(*upload_tasks)
        
        return await self.finalize_upload(file_path, caption)
    
    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Check if this uploader can handle the given file"""
        pass
    
    async def cleanup(self):
        """Cleanup resources"""
        self._chunk_executor.shutdown(wait=True)

class FileUploadService:
    """Handles all file upload operations with optimized performance"""
    
    def __init__(self, config: UploadConfig):
        self.config = config
        self.uploaders: Dict[str, UploaderBase] = {}
        self._upload_semaphore = asyncio.Semaphore(config.max_concurrent_uploads)
        self._active_uploads: Dict[str, asyncio.Task] = {}
    
    def register_uploader(self, name: str, uploader: UploaderBase):
        """Register a new uploader"""
        self.uploaders[name] = uploader
    
    @lru_cache(maxsize=100)
    def _get_file_size(self, file_path: Path) -> int:
        """Get file size with caching"""
        return file_path.stat().st_size if file_path.exists() else 0
    
    def _select_uploader(self, file_path: Path, method: str) -> Optional[UploaderBase]:
        """Select the most appropriate uploader based on file size and type"""
        if method != 'auto':
            return self.uploaders.get(method)
        
        file_size = self._get_file_size(file_path)
        
        # Use Bot API for small files
        if file_size <= self.config.bot_api_max_size:
            if 'bot_api' in self.uploaders and self.uploaders['bot_api'].can_handle(file_path):
                return self.uploaders['bot_api']
        
        # Use Telethon for large files
        if 'telethon' in self.uploaders and self.uploaders['telethon'].can_handle(file_path):
            return self.uploaders['telethon']
        
        # Try other uploaders as fallback
        for uploader in self.uploaders.values():
            if uploader.can_handle(file_path):
                return uploader
        
        return None
    
    async def upload_file(
        self, 
        file_path: Path, 
        caption: Optional[str] = None,
        method: str = 'auto',
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> UploadResult:
        """
        Upload a file with optimized handling and progress tracking
        
        Args:
            file_path: Path to the file to upload
            caption: Optional caption for the media
            method: Upload method ('auto', 'bot_api', or 'telethon')
            progress_callback: Optional callback for upload progress
        
        Returns:
            UploadResult: Upload result with details
        """
        if not file_path.exists():
            return UploadResult(False, error="File not found")
        
        file_key = str(file_path.absolute())
        
        # Check if upload already in progress
        if file_key in self._active_uploads:
            logger.warning(f"Upload already in progress for {file_path}")
            try:
                return await self._active_uploads[file_key]
            except Exception as e:
                return UploadResult(False, error=f"Concurrent upload failed: {str(e)}")
        
        uploader = self._select_uploader(file_path, method)
        if not uploader:
            return UploadResult(False, error="No suitable uploader found")
        
        async with self._upload_semaphore:
            try:
                # Create upload task
                upload_task = asyncio.create_task(
                    uploader.upload(file_path, caption)
                )
                self._active_uploads[file_key] = upload_task
                
                # Wait for upload with timeout
                result = await asyncio.wait_for(upload_task, UPLOAD_TIMEOUT)
                return result
                
            except asyncio.TimeoutError:
                return UploadResult(False, error="Upload timeout")
            except Exception as e:
                logger.error(f"Upload failed: {str(e)}", exc_info=True)
                return UploadResult(False, error=str(e))
            finally:
                self._active_uploads.pop(file_key, None)
    
    async def cleanup(self):
        """Cleanup service resources"""
        cleanup_tasks = []
        for uploader in self.uploaders.values():
            cleanup_tasks.append(uploader.cleanup())
        
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks)
