"""Integrated rate limiting and smart backoff for Instagram downloads."""
import asyncio
import logging
import time
import random
from typing import Any, Callable, TypeVar, Optional
from functools import wraps
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

T = TypeVar('T')

class InstagramRateLimit:
    """Configuration constants for Instagram rate limiting"""
    REQUESTS_PER_HOUR = 100
    MIN_REQUEST_INTERVAL = 6.0
    BATCH_DELAY = 30.0
    BACKOFF_INITIAL = 10.0
    BACKOFF_MAX = 1800.0  # 30 minutes
    BACKOFF_MULTIPLIER = 2.0
    BACKOFF_JITTER = 0.1
    SESSION_MAX_REQUESTS = 50
    SESSION_ROTATE_INTERVAL = 3600  # 1 hour

class SmartDownloadManager:
    """Manages download operations with rate limiting and backoff"""
    
    def __init__(self):
        self.last_request_time = 0.0
        self.request_count = 0
        self.error_count = 0
        self.session_start_time = datetime.now()
        self.session_request_count = 0
        self.in_conservative_mode = False
        self._request_history = {}
        
    def _add_jitter(self, delay: float) -> float:
        """Add random jitter to delay"""
        jitter = delay * InstagramRateLimit.BACKOFF_JITTER
        return delay + random.uniform(-jitter, jitter)
        
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time with jitter"""
        delay = min(
            InstagramRateLimit.BACKOFF_INITIAL * 
            (InstagramRateLimit.BACKOFF_MULTIPLIER ** attempt),
            InstagramRateLimit.BACKOFF_MAX
        )
        return self._add_jitter(delay)
        
    def should_rotate_session(self) -> bool:
        """Check if we should rotate the session"""
        session_age = datetime.now() - self.session_start_time
        return (
            session_age.total_seconds() >= InstagramRateLimit.SESSION_ROTATE_INTERVAL or
            self.session_request_count >= InstagramRateLimit.SESSION_MAX_REQUESTS
        )
        
    async def wait_before_request(self, is_batch: bool = False) -> None:
        """Smart wait before making a request"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # Base delay calculation
        base_delay = max(0, InstagramRateLimit.MIN_REQUEST_INTERVAL - time_since_last)
        
        # Additional delay for batch operations
        if is_batch:
            base_delay = max(base_delay, InstagramRateLimit.BATCH_DELAY)
            
        # Extra delay in conservative mode
        if self.in_conservative_mode:
            base_delay *= 2
            
        # Add jitter and wait
        delay = self._add_jitter(base_delay)
        if delay > 0:
            await asyncio.sleep(delay)
            
        # Update tracking
        self.last_request_time = time.time()
        self.request_count += 1
        self.session_request_count += 1
        
    def handle_error(self, error: Exception) -> float:
        """Handle error and return backoff time"""
        self.error_count += 1
        
        # Analyze error type
        error_str = str(error).lower()
        if any(phrase in error_str for phrase in [
            "rate limit", "too many requests", "429"
        ]):
            self.in_conservative_mode = True
            return self._calculate_backoff(self.error_count)
            
        elif any(phrase in error_str for phrase in [
            "blocked", "suspicious", "unusual activity"
        ]):
            self.in_conservative_mode = True
            return InstagramRateLimit.BACKOFF_MAX
            
        return self._calculate_backoff(min(self.error_count, 3))

def with_smart_download(batch: bool = False, max_retries: int = 3):
    """Decorator for smart download handling with retries."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(self, *args: Any, **kwargs: Any) -> Any:
            if not hasattr(self, '_download_manager'):
                self._download_manager = SmartDownloadManager()
                
            for attempt in range(max_retries):
                # Check session rotation
                if self._download_manager.should_rotate_session():
                    await self.refresh_session()
                    self._download_manager.session_start_time = datetime.now()
                    self._download_manager.session_request_count = 0
                    
                # Wait before request
                await self._download_manager.wait_before_request(batch)
                
                try:
                    return await func(self, *args, **kwargs)
                except Exception as e:
                    backoff_time = self._download_manager.handle_error(e)
                    if attempt == max_retries - 1:  # Last attempt
                        logger.error(f"All {max_retries} attempts failed: {str(e)}")
                        raise
                    logger.warning(
                        f"Download failed (attempt {attempt + 1}/{max_retries}), "
                        f"backing off for {backoff_time:.1f}s: {str(e)}"
                    )
                    await asyncio.sleep(backoff_time)
            
            raise RuntimeError("Should not reach here")
                
        return wrapper
    return decorator