"""Instagram session manager module."""
import logging
import os
import json
from pathlib import Path
import browser_cookie3
from gallery_dl import config, job, util

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class InstagramSessionError(Exception):
    """Custom exception for Instagram session errors."""
    pass

class InstagramSessionManager:
    """Manages Instagram sessions using gallery-dl."""
    
    def __init__(self, download_path: Path, username: str):
        """Initialize the session manager.
        
        Args:
            download_path (Path): Path where downloads and session files are stored
            username (str): Instagram username for authentication
        """
        self.download_path = download_path
        self.username = username
        self.config_file = Path("gallery-dl.conf")
        
        # Create downloads directory
        self.download_path.mkdir(parents=True, exist_ok=True)
        
        # Configure gallery-dl
        self._configure_gallery_dl()
    
    def _configure_gallery_dl(self):
        """Configure gallery-dl with proper settings."""
        config_data = {
            "extractor": {
                "instagram": {
                    "directory": str(self.download_path),
                    "filename": "{date:%Y-%m-%d_%H-%M-%S}_Instagram_{shortcode}_{num}.{extension}",
                    "metadata": True,
                    "videos": True,
                    "cookies-from-browser": "firefox",
                    "browser": "firefox",
                    "cookies-update": True,  # Changed to True to update cookies
                    "postprocessors": [
                        {
                            "name": "metadata",
                            "mode": "json",
                            "whitelist": ["date", "shortcode", "description", "tags"]
                        }
                    ]
                }
            },
            "output": {
                "mode": "terminal",
                "progress": True,
                "shorten": True,
                "log": str(self.download_path / "gallery-dl.log")
            },
            "cache": {
                "file": str(self.download_path / ".gallery-dl.cache")
            }
        }
        
        # Save configuration
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=4)
            
        # Load configuration
        config.load([str(self.config_file)])
    
    def _init_browser_session(self) -> bool:
        """Initialize browser cookie session by checking Firefox cookies directly.
        
        Returns:
            bool: True if valid session found
        """
        try:
            # Check if Firefox has Instagram cookies
            cookies = browser_cookie3.firefox(domain_name="instagram.com")
            session_found = False
            csrf_found = False
            
            for cookie in cookies:
                if cookie.name == "sessionid" and cookie.value:
                    session_found = True
                    logger.info(f"Found sessionid cookie: {cookie.value[:10]}...")
                if cookie.name == "csrftoken" and cookie.value:
                    csrf_found = True
                    logger.info(f"Found csrftoken cookie: {cookie.value[:10]}...")
            
            if session_found and csrf_found:
                logger.info("Successfully found Instagram session cookies in Firefox")
                return True
            else:
                missing = []
                if not session_found:
                    missing.append("sessionid")
                if not csrf_found:
                    missing.append("csrftoken")
                logger.error(f"Missing required cookies: {', '.join(missing)}")
                return False
                
        except Exception as e:
            logger.error(f"Failed to load Firefox cookies: {e}")
            return False
    
    def check_session(self) -> bool:
        """Check if the session is valid.
        
        Returns:
            bool: True if valid session found
        """
        return self._init_browser_session()
    
    def create_job(self, url: str) -> job.Job:
        """Create a gallery-dl job for downloading.
        
        Args:
            url (str): The URL to download from
            
        Returns:
            job.Job: Configured gallery-dl job instance
        
        Raises:
            InstagramSessionError: If no valid session found
        """
        if not self._init_browser_session():
            raise InstagramSessionError(
                "No valid Instagram session found. Please login to Instagram in Firefox and try again."
            )
            
        try:
            # Create gallery-dl job with updated config
            return job.Job(url)
        except Exception as e:
            raise InstagramSessionError(f"Failed to create download job: {e}")
    
    def debug_cookies(self):
        """Debug method to check what cookies are available."""
        try:
            cookies = browser_cookie3.firefox(domain_name="instagram.com")
            logger.info("Available Instagram cookies in Firefox:")
            for cookie in cookies:
                logger.info(f"Cookie: {cookie.name} = {cookie.value[:10]}... (domain: {cookie.domain})")
            
            if not any(cookie.name == "sessionid" for cookie in cookies):
                logger.warning("No sessionid cookie found - user may not be logged in")
                
        except Exception as e:
            logger.error(f"Failed to debug cookies: {e}")
