import asyncio
import logging
import re
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import json
import subprocess
from datetime import datetime, timedelta
from instaloader import (
    Instaloader, Post, Profile, Story, StoryItem,
    Highlight, NodeIterator, InstaloaderException
)
from ..core.config import InstagramConfig
from ..core.retry import RetryableOperation

logger = logging.getLogger(__name__)

class InstagramDownloadError(Exception):
    """Custom exception for Instagram download errors"""
    pass

class InstagramDownloader:
    """Handles downloading content from Instagram"""
    
    def __init__(self, config: InstagramConfig, downloads_path: Path):
        self.config = config
        self.downloads_path = downloads_path
        self.downloads_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize Instaloader with common settings
        self.instaloader = Instaloader(
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=True,
            compress_json=False
        )
        
        # Load cookies from Firefox
        try:
            # Initialize the context with cookies
            import browser_cookie3
            
            # Get Instagram cookies from Firefox
            cookies = browser_cookie3.firefox(domain_name=".instagram.com")
            cookie_dict = {cookie.name: cookie.value for cookie in cookies}
            
            # Set cookies in Instaloader
            self.instaloader.context._session.cookies.update(cookie_dict)
            logger.info("Successfully loaded session from Firefox cookies")
        except Exception as e:
            logger.warning(f"Failed to load session from Firefox: {e}")
        
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
            # Try instaloader first since we have browser cookies
            files = await self._download_with_instaloader(url)
            if files:
                return files
                
            # Fall back to gallery-dl as backup
            logger.info("Instaloader failed, trying gallery-dl...")
            return await self._download_with_gallery_dl(url)
            
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}", exc_info=True)
            raise InstagramDownloadError(f"Failed to download {url}: {str(e)}")
    
    async def _download_with_gallery_dl(self, url: str) -> List[Path]:
        """Download using gallery-dl"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = self.downloads_path / timestamp
        
        cmd = [
            "gallery-dl",
            "--write-metadata",
            "--download-archive", str(self.downloads_path / ".gallery-dl-archive"),
            "--cookies-from-browser", "firefox",  # Use Firefox cookies
            "-D", str(output_path),
            url
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.download_timeout
            )
            
            if process.returncode != 0:
                logger.error(f"gallery-dl error: {stderr.decode()}")
                return []
                
            # Find downloaded files
            if output_path.exists():
                files = list(output_path.rglob("*"))
                files = [f for f in files if f.is_file() and not f.name.endswith(".json")]
                if files:
                    return files
                    
            return []
            
        except asyncio.TimeoutError:
            logger.error("gallery-dl download timed out")
            return []
        except Exception as e:
            logger.error(f"gallery-dl error: {e}", exc_info=True)
            return []
    
    async def _download_with_instaloader(self, url: str) -> List[Path]:
        """Download using instaloader"""
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_path = self.downloads_path / timestamp
        output_path.mkdir(parents=True, exist_ok=True)
        
        try:
            # Set output directory for this download
            self.instaloader.dirname_pattern = str(output_path)
            
            # Extract post shortcode from URL
            # Handle both /p/ and /reel/ URLs
            if "/p/" in url:
                shortcode = url.split("/p/")[1].split("/")[0]
            elif "/reel/" in url:
                shortcode = url.split("/reel/")[1].split("/")[0]
            else:
                raise ValueError("Invalid Instagram URL. Must be a post or reel URL")
                
            # Download the post
            post = Post.from_shortcode(self.instaloader.context, shortcode)
            self.instaloader.download_post(post, target=str(output_path))
            
            # Find downloaded files
            files = list(output_path.rglob("*"))
            files = [f for f in files if f.is_file() and not f.name.endswith(".json") and not f.name.endswith(".txt")]
            return files
            
        except Exception as e:
            logger.error(f"instaloader error: {e}", exc_info=True)
            return []
            
    async def _extract_metadata(self, path: Path) -> Dict[str, Any]:
        """Extract metadata from downloaded files"""
        try:
            json_files = list(path.parent.glob("*.json"))
            if not json_files:
                return {}
                
            with open(json_files[0], 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to extract metadata: {e}")
            return {}
