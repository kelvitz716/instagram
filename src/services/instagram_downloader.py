import asyncio
import logging
import re
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from ..core.config import InstagramConfig
from ..core.retry import RetryableOperation
from ..core.session_manager import InstagramSessionManager, InstagramSessionError

logger = logging.getLogger(__name__)

class InstagramDownloadError(Exception):
    """Custom exception for Instagram download errors"""
    pass

class InstagramDownloader:
    """Handles downloading content from Instagram using gallery-dl with Firefox cookies.
    
    This downloader supports:
    - Posts (single image/video)
    - Reels
    - Carousels (multiple images/videos)
    
    Note: Stories and highlights are not supported as they require Instagram's private API access.
    """
    
    def __init__(self, config: InstagramConfig, downloads_path: Path):
        """Initialize the Instagram downloader.
        
        Args:
            config: Configuration for the downloader
            downloads_path: Path where downloads will be stored
        """
        self.config = config
        self.downloads_path = downloads_path
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize session manager
        try:
            self.session_manager = InstagramSessionManager(downloads_path, config.username)
        except InstagramSessionError as e:
            logger.error(f"Failed to initialize sessions: {e}")
            raise
            
        # Path to gallery-dl executable
        self.gallery_dl_path = Path("/home/kelvitz/Github/instagram/myenv/bin/gallery-dl")
        
    def _check_session_before_download(self) -> bool:
        """Check if we have a valid session before attempting download."""
        try:
            # Use the session manager's debug method to check cookies
            self.session_manager.debug_cookies()
            return self.session_manager.check_session()
        except Exception as e:
            logger.error(f"Session check failed: {e}")
            return False
    
    @RetryableOperation(max_retries=3, backoff_factor=20.0)
    async def download_post(self, url: str) -> List[Path]:
        """
        Download content from an Instagram post URL
        
        Args:
            url: Instagram post URL
            
        Returns:
            List[Path]: Paths to downloaded files
            
        Raises:
            InstagramDownloadError: If download fails
        """
        try:
            # Check session before attempting download
            if not self._check_session_before_download():
                raise InstagramSessionError(
                    "No valid Instagram session found. Please login to Instagram in Firefox and try again."
                )
            
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            output_path = self.downloads_path / timestamp
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Clean up the URL
            url = url.split("?")[0]  # Remove query parameters
            
            # Prepare gallery-dl command with more verbose output
            cmd = [
                str(self.gallery_dl_path),
                '--cookies-from-browser', 'firefox',
                '--write-metadata',
                '--verbose',  # Add verbose output for better debugging
                '-D', str(output_path),
                url
            ]
            
            logger.info(f"Running gallery-dl command: {' '.join(cmd)}")
            
            # Run gallery-dl command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            # Log the full output for debugging
            if result.stdout:
                logger.info(f"gallery-dl stdout: {result.stdout}")
            if result.stderr:
                logger.info(f"gallery-dl stderr: {result.stderr}")
            
            # Check for specific error conditions
            if result.returncode != 0:
                error_msg = result.stderr.lower()
                
                if any(phrase in error_msg for phrase in [
                    "http redirect to login page",
                    "login required",
                    "authentication failed",
                    "403 forbidden",
                    "401 unauthorized"
                ]):
                    raise InstagramSessionError(
                        "Instagram authentication failed. Please login to Instagram in Firefox and try again."
                    )
                elif "private account" in error_msg:
                    raise InstagramDownloadError(f"Cannot download from private account: {url}")
                elif "not found" in error_msg or "404" in error_msg:
                    raise InstagramDownloadError(f"Content not found: {url}")
                else:
                    raise InstagramDownloadError(f"gallery-dl failed with code {result.returncode}: {result.stderr}")
                
            # Find downloaded files
            files = self._find_downloaded_files(output_path)
            
            if not files:
                # Check if gallery-dl actually ran but didn't download anything
                if "already exists" in result.stdout.lower():
                    logger.warning("Files may have been previously downloaded")
                    # Try to find files in the download directory
                    files = self._find_downloaded_files(self.downloads_path)
                
                if not files:
                    raise InstagramDownloadError(f"No files were downloaded from {url}")
                
            logger.info(f"Successfully downloaded {len(files)} file(s) from {url}")
            return files
            
        except subprocess.TimeoutExpired:
            logger.error(f"Download timed out for {url}")
            raise InstagramDownloadError(f"Download timed out for {url}")
        except InstagramSessionError:
            # Re-raise session errors as-is
            raise
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}", exc_info=True)
            raise InstagramDownloadError(f"Failed to download {url}: {str(e)}")
    
    def _find_downloaded_files(self, search_path: Path) -> List[Path]:
        """Find downloaded media files in the given path."""
        if not search_path.exists():
            return []
            
        # Look for common media file extensions
        media_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.mp4', '.mov', '.avi', '.webm'}
        files = []
        
        for file_path in search_path.rglob("*"):
            if (file_path.is_file() and 
                file_path.suffix.lower() in media_extensions and
                not file_path.name.startswith('.')):  # Skip hidden files
                files.append(file_path)
        
        # Sort files by modification time (newest first)
        files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return files
            
    async def _extract_metadata(self, path: Path) -> Dict[str, Any]:
        """Extract metadata from downloaded files"""
        try:
            # Look for JSON metadata files
            json_files = list(path.parent.glob("*.json"))
            if not json_files:
                # Try looking in the same directory as the media file
                json_files = list(path.with_suffix('.json').parent.glob(f"{path.stem}*.json"))
                
            if json_files:
                with open(json_files[0], 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"No metadata file found for {path}")
                return {}
        except Exception as e:
            logger.error(f"Failed to extract metadata: {e}")
            return {}
    
    async def extract_username_from_url(self, url: str) -> Optional[str]:
        """
        Extract username from an Instagram URL
        
        Args:
            url: Instagram URL (profile or post)
            
        Returns:
            Optional[str]: Username if found, None otherwise
        """
        patterns = [
            r"(?:instagram\.com/|@)([A-Za-z0-9_.]+)/?$",  # Profile URL or @mention
            r"instagram\.com/([A-Za-z0-9_.]+)/(?:p|reel)/",  # Post/Reel URL
        ]
        
        for pattern in patterns:
            if match := re.search(pattern, url):
                username = match.group(1)
                # Filter out known Instagram paths that aren't usernames
                if username not in ['p', 'reel', 'stories', 'tv', 'explore', 'accounts', 'direct']:
                    return username
        return None
    
    async def test_session(self) -> Tuple[bool, str]:
        """
        Test if the current session is working by attempting to fetch Instagram homepage.
        
        Returns:
            Tuple[bool, str]: (success, message)
        """
        try:
            cmd = [
                str(self.gallery_dl_path),
                '--cookies-from-browser', 'firefox',
                '--simulate',  # Don't actually download anything
                'https://www.instagram.com/'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                return True, "Session is valid"
            else:
                error_msg = result.stderr.lower()
                if any(phrase in error_msg for phrase in [
                    "http redirect to login page",
                    "login required",
                    "authentication failed"
                ]):
                    return False, "Session expired or invalid. Please login to Instagram in Firefox."
                else:
                    return False, f"Unknown error: {result.stderr}"
                    
        except subprocess.TimeoutExpired:
            return False, "Session test timed out"
        except Exception as e:
            return False, f"Session test failed: {str(e)}"