"""Session manager for Instagram cookie management using Netscape format cookies file."""
import logging
import os
import time
import shutil
from pathlib import Path
from typing import Dict, Optional, Tuple
import requests
from datetime import datetime, timedelta

# Configure logging
logger = logging.getLogger(__name__)

class InstagramSessionError(Exception):
    """Exception raised for Instagram session errors."""
    def __init__(self, message: str, is_rate_limit: bool = False):
        super().__init__(message)
        self.is_rate_limit = is_rate_limit

class InstagramSessionManager:
    """Manages Instagram sessions using Netscape-format cookies."""

    REQUIRED_COOKIES = ['sessionid', 'csrftoken']
    COOKIE_DOMAIN = '.instagram.com'
    MANUAL_CHECK_THRESHOLD = timedelta(minutes=10)  # If cookies refreshed within this time, might be rate limiting
    SESSION_REFRESH_URL = 'https://www.instagram.com/accounts/login/ajax/'

    def __init__(self, downloads_path: Path, cookies_file: Optional[Path] = None):
        """Initialize the session manager.
        
        Args:
            downloads_path: Path where downloads will be stored
            cookies_file: Path to a Netscape-format cookies.txt file containing Instagram session cookies
        """
        self.downloads_path = downloads_path
        self.cookies_file = cookies_file
        self._session_cookies: Dict[str, str] = {}
        self._last_cookie_refresh = None  # Timestamp of last successful cookie refresh
        self._is_valid = False
        if cookies_file and cookies_file.exists():
            self._load_cookies()

    async def load_cookies_from_file(self, file_path: Path) -> Dict[str, str]:
        """Load cookies from a file and store them in the configured location.
        
        Args:
            file_path: Path to the cookie file to load
            
        Returns:
            Dict containing the session cookies
            
        Raises:
            InstagramSessionError: If cookies are invalid or can't be loaded
        """
        try:
            # Make sure the file exists
            if not file_path.exists():
                raise InstagramSessionError("Cookie file not found")

            # Parse cookies from file
            cookies = self._load_netscape_cookies(file_path)
            session_cookies = {}

            # Extract Instagram cookies
            for cookie in cookies:
                if cookie['domain'].endswith(self.COOKIE_DOMAIN):
                    masked_value = f"{str(cookie['value'])[:10]}..."
                    logger.debug(f"Found cookie: {cookie['name']} = {masked_value}")
                    session_cookies[cookie['name']] = cookie['value']

            # Validate required cookies are present
            missing_cookies = [name for name in self.REQUIRED_COOKIES 
                             if name not in session_cookies]
                             
            if missing_cookies:
                raise InstagramSessionError(
                    f"Missing required cookies: {', '.join(missing_cookies)}"
                )

            # If file is not already in the configured location, copy it
            if file_path != self.cookies_file:
                os.makedirs(os.path.dirname(self.cookies_file), exist_ok=True)
                shutil.copy2(file_path, self.cookies_file)
            
            # Load the cookies into the manager
            self._session_cookies = session_cookies
            self._last_cookie_refresh = datetime.now()
            self._is_valid = True

            return session_cookies

        except Exception as e:
            raise InstagramSessionError(f"Failed to load cookies: {str(e)}")

    async def is_valid(self) -> bool:
        """Check if the current session is valid."""
        try:
            if not self._session_cookies:
                return False
                
            # Check if we have required cookies
            missing_cookies = [name for name in self.REQUIRED_COOKIES 
                             if name not in self._session_cookies]
            if missing_cookies:
                return False
                
            # Check if cookies file exists
            if not self.cookies_file or not self.cookies_file.exists():
                return False
                
            # If we haven't checked validity recently, do a quick test
            if not self._last_cookie_refresh or \
               datetime.now() - self._last_cookie_refresh > timedelta(hours=1):
                try:
                    # Make a test request to Instagram
                    response = requests.get(
                        'https://www.instagram.com/data/shared_data/',
                        cookies=self._session_cookies,
                        timeout=10
                    )
                    
                    if response.status_code != 200 or '"authenticated":false' in response.text:
                        self._is_valid = False
                        return False
                        
                    self._is_valid = True
                    self._last_cookie_refresh = datetime.now()
                    
                except Exception as e:
                    logger.warning(f"Session validation failed: {e}")
                    self._is_valid = False
                    return False
                    
            return self._is_valid
            
        except Exception as e:
            logger.error(f"Error checking session validity: {e}")
            return False
            
    def _load_cookies(self, max_retries: int = 3, initial_delay: float = 1.0) -> None:
        """Load cookies from Netscape file and validate them with retries."""
        last_error = None
        delay = initial_delay

        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"Retrying cookie load (attempt {attempt}/{max_retries})")

                if not self.cookies_file.exists():
                    raise InstagramSessionError("No cookies.txt file found at specified path. Please provide a valid Netscape-format cookies.txt file.")

                logger.info(f"Loading Instagram cookies from Netscape-format file: {self.cookies_file}")
                cookies = self._load_netscape_cookies(self.cookies_file)

                # Clear existing cookies
                old_cookies = self._session_cookies.copy()
                self._session_cookies.clear()

                # Load new cookies from Netscape format
                for cookie in cookies:
                    if cookie['domain'].endswith(self.COOKIE_DOMAIN):
                        masked_value = f"{str(cookie['value'])[:10]}..."
                        logger.debug(f"Found cookie: {cookie['name']} = {masked_value}")
                        self._session_cookies[cookie['name']] = cookie['value']

                # Check if cookies actually changed
                if self._session_cookies != old_cookies:
                    self._last_cookie_refresh = datetime.now()
                    logger.info("Cookies were refreshed")
                elif not self._session_cookies:
                    raise InstagramSessionError("No Instagram cookies found in cookies.txt file.")

                # Verify and log found cookies
                self._validate_cookies()

                logger.info("Successfully loaded Instagram cookies")
                return  # Success!

            except InstagramSessionError as e:
                if e.is_rate_limit:
                    raise  # Don't retry rate limit errors
                last_error = str(e)
                logger.warning(f"Cookie load attempt {attempt + 1} failed: {last_error}")
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Cookie load attempt {attempt + 1} failed: {last_error}")

            if attempt < max_retries:
                import time
                time.sleep(delay)
                delay *= 2  # Exponential backoff

        # All retries failed
        error_msg = f"Failed to load Instagram cookies after {max_retries} attempts. Last error: {last_error}"
        logger.error(error_msg)
        raise InstagramSessionError(error_msg)

    @staticmethod
    def _load_netscape_cookies(file_path: Path) -> list:
        """Parse a Netscape-format cookies.txt file and return a list of cookies."""
        cookies = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith('#') or not line.strip():
                        continue
                    parts = line.strip().split('\t')
                    if len(parts) == 7:
                        domain, flag, path, secure, expires, name, value = parts
                        cookies.append({
                            'domain': domain,
                            'name': name,
                            'value': value,
                            'path': path,
                            'secure': secure == 'TRUE',
                            'expires': int(expires) if expires.isdigit() else None
                        })
        except Exception as e:
            logger.error(f"Failed to parse Netscape cookies file: {e}")
        return cookies
    

    
    def _validate_cookies(self) -> None:
        """Validate required cookies and log their presence.
        
        Raises:
            InstagramSessionError: If required cookies are missing
        """
        for cookie_name in self.REQUIRED_COOKIES:
            if cookie_name in self._session_cookies:
                masked_value = f"{str(self._session_cookies[cookie_name])[:10]}..."
                logger.debug(f"Found {cookie_name} cookie: {masked_value}")
            
        missing_cookies = [name for name in self.REQUIRED_COOKIES 
                         if name not in self._session_cookies]
                         
        if missing_cookies:
            error_msg = f"Missing required cookies: {', '.join(missing_cookies)}"
            logger.error(error_msg)
            
            # Check if cookies were recently refreshed
            if (self._last_cookie_refresh and 
                datetime.now() - self._last_cookie_refresh < self.MANUAL_CHECK_THRESHOLD):
                error_msg = (
                    f"Cookies were refreshed {(datetime.now() - self._last_cookie_refresh).total_seconds():.0f} "
                    "seconds ago but still invalid. Please check if Instagram is "
                    "accessible in Firefox and refresh the page to update cookies."
                )
                raise InstagramSessionError(error_msg, is_rate_limit=True)
            
            raise InstagramSessionError(
                "Session expired. Will try to refresh cookies from Firefox."
            )
    
    async def refresh_session(self) -> bool:
        """Refresh session by reloading cookies from Firefox.
        
        Returns:
            bool: True if refresh was successful, False otherwise
        """
        try:
            # Reload cookies from Firefox
            self._load_cookies()
            
            # Validate current cookies
            self._validate_cookies()
            
            # Test session validity
            valid, msg = await self._test_session()
            if not valid:
                logger.warning(f"Session test failed after refresh: {msg}")
                return False
                
            return True
            
        except InstagramSessionError as e:
            if e.is_rate_limit:
                raise  # Re-raise rate limit errors
            logger.error(f"Session refresh failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during session refresh: {e}")
            return False
    
    async def _test_session(self, max_retries: int = 3) -> Tuple[bool, str]:
        """Test if the current session is valid by making a test request.
        
        Args:
            max_retries: Maximum number of retry attempts
            
        Returns:
            Tuple[bool, str]: (is_valid, message)
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json',
            'X-CSRFToken': self._session_cookies.get('csrftoken', ''),
            'X-Requested-With': 'XMLHttpRequest'
        }
        
        cookies = {name: value for name, value in self._session_cookies.items()}
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    logger.info(f"Retrying session test (attempt {attempt}/{max_retries})")
                    
                response = requests.get(
                    'https://www.instagram.com/data/shared_data/',
                    headers=headers,
                    cookies=cookies,
                    timeout=10 + (attempt * 5)  # Increase timeout with each retry
                )
                
                if response.status_code == 200 and 'config' in response.json():
                    return True, "Session is valid"
                elif response.status_code == 429:
                    msg = "Rate limited by Instagram. Please wait a few minutes."
                    logger.warning(msg)
                    return False, msg
                else:
                    last_error = f"Invalid response: {response.status_code}"
                    
            except requests.exceptions.Timeout:
                last_error = "Request timed out. Instagram might be slow or network issues."
                logger.warning(f"Session test attempt {attempt + 1} failed: {last_error}")
            except requests.exceptions.ConnectionError:
                last_error = "Network connection error. Please check your internet connection."
                logger.warning(f"Session test attempt {attempt + 1} failed: {last_error}")
            except Exception as e:
                last_error = f"Test failed: {str(e)}"
                logger.warning(f"Session test attempt {attempt + 1} failed: {last_error}")
            
            if attempt < max_retries:
                import time
                time.sleep(2 ** attempt)  # Exponential backoff: 1, 2, 4, 8 seconds
                continue
            
            return False, f"Session test failed after {max_retries} attempts. Last error: {last_error}"
            
    def debug_cookies(self) -> None:
        """Debug helper to log all available Instagram cookies."""
        logger.info("Available Instagram cookies:")
        for name, value in self._session_cookies.items():
            if name in self.REQUIRED_COOKIES:
                masked_value = f"{str(value)[:10]}..."
                logger.info(f"Cookie: {name} = {masked_value} (domain: {self.COOKIE_DOMAIN})")
    
    def check_session(self) -> bool:
        """Check if we have all required cookies."""
        try:
            self._validate_cookies()
            return True
        except InstagramSessionError:
            return False
            
    async def clear_session(self) -> None:
        """Clear the current session data and remove cookies."""
        try:
            # Clear memory state
            self._session_cookies.clear()
            self._is_valid = False
            self._last_cookie_refresh = None
            
            # Remove cookies file if it exists
            if self.cookies_file and self.cookies_file.exists():
                self.cookies_file.unlink()
            
            logger.info("Session cleared successfully")
        except Exception as e:
            logger.error(f"Error clearing session: {e}")
            raise InstagramSessionError(f"Failed to clear session: {e}")
