"""Instagram-specific rate limiting implementation."""
import time
import random
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

from .config import RateLimitConfig

logger = logging.getLogger(__name__)

class InstagramRateLimiter:
    """Handles rate limiting for Instagram API requests."""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config = RateLimitConfig(
            config_path or Path('config/rate_limiting.conf')
        )
        self.last_request_time = 0.0
        self.request_count = 0
        self.error_count = 0
        self.session_start_time = datetime.now()
        self.session_request_count = 0
        self.in_conservative_mode = False
        self.conservative_mode_start: Optional[datetime] = None
        self._request_history: Dict[float, str] = {}
        self.request_history = {}
        
    def _add_jitter(self, delay: float) -> float:
        """Add random jitter to delay to avoid synchronized requests."""
        jitter = delay * self.config.BACKOFF_JITTER
        return delay + random.uniform(-jitter, jitter)
        
    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time with exponential increase."""
        delay = min(
            self.config.INITIAL_BACKOFF * 
            (self.config.BACKOFF_MULTIPLIER ** attempt),
            self.config.MAX_BACKOFF
        )
        return self._add_jitter(delay)
        
    def should_rotate_session(self) -> bool:
        """Check if the current session should be rotated."""
        session_age = datetime.now() - self.session_start_time
        return (
            session_age.total_seconds() >= self.config.SESSION_ROTATE_INTERVAL or
            self.session_request_count >= self.config.MAX_REQUESTS_PER_SESSION
        )
        
    def enter_conservative_mode(self):
        """Enter conservative mode after detecting potential issues."""
        self.in_conservative_mode = True
        self.conservative_mode_start = datetime.now()
        logger.warning(
            f"Entering conservative mode for {self.config.CONSERVATIVE_MODE_DURATION} seconds"
        )
        
    def exit_conservative_mode(self):
        """Check and potentially exit conservative mode."""
        if self.conservative_mode_start:
            elapsed = datetime.now() - self.conservative_mode_start
            if elapsed.total_seconds() >= self.config.CONSERVATIVE_MODE_DURATION:
                self.in_conservative_mode = False
                self.error_count = 0
                logger.info("Exiting conservative mode")
                
    async def wait_for_request(self, request_type: str = 'normal') -> None:
        """Smart wait before making a request to Instagram."""
        current_time = time.time()
        
        # Check and potentially exit conservative mode
        self.exit_conservative_mode()
        
        # Calculate base delay
        time_since_last = current_time - self.last_request_time
        base_delay = max(0, self.config.INSTAGRAM_MIN_REQUEST_INTERVAL - time_since_last)
        
        # Always ensure at least minimum interval
        base_delay = max(base_delay, self.config.INSTAGRAM_MIN_REQUEST_INTERVAL)
        
        # Adjust delay based on conditions
        if self.in_conservative_mode:
            base_delay *= 2  # Double the delay in conservative mode
            
        if request_type == 'batch':
            base_delay = max(base_delay, self.config.INSTAGRAM_BATCH_DELAY)
        
        # Check recent request count and add cumulative delay for bursts
        recent_requests = len([ts for ts in self.request_history if ts >= current_time - 10])
        burst_count = recent_requests + 1  # Include current request
        
        # Enforce minimum delay between operations proportional to burst count
        if burst_count > self.config.INSTAGRAM_MAX_BURST_REQUESTS:
            # Base multiplier starts at 1.2 for being over burst limit
            multiplier = 1.2
            # Add 0.1 for each request over burst limit
            multiplier += 0.1 * (burst_count - self.config.INSTAGRAM_MAX_BURST_REQUESTS)
            
            # Ensure the base delay is at least 10% higher than normal
            base_delay = max(base_delay * multiplier, self.config.INSTAGRAM_MIN_REQUEST_INTERVAL * 1.1)
            
            # If we're way over burst limits, add additional delay
            if burst_count >= self.config.INSTAGRAM_MAX_BURST_REQUESTS * 2:
                base_delay *= 1.5
        
        # Add jitter for more natural timing
        delay = self._add_jitter(base_delay)
        
        # Wait the calculated time
        if delay > 0:
            await asyncio.sleep(delay)
            
        # Update tracking before waiting to capture request timing
        new_time = time.time()
        self.last_request_time = new_time
        self.request_count += 1
        self.session_request_count += 1
        self.request_history[new_time] = request_type
        
        # Clean old history
        self._clean_history()
        
    def _clean_history(self):
        """Clean request history older than 1 hour."""
        threshold = time.time() - 3600
        self.request_history = {
            ts: rt for ts, rt in self.request_history.items()
            if ts > threshold
        }
        
    def handle_error(self, error: Exception) -> float:
        """Handle different types of errors with appropriate backoff."""
        self.error_count += 1
        error_str = str(error).lower()
        
        # Analyze error type and determine backoff strategy
        if any(phrase in error_str for phrase in [
            "rate limit", "too many requests", "429"
        ]):
            self.enter_conservative_mode()
            return self._calculate_backoff(self.error_count)
            
        elif any(phrase in error_str for phrase in [
            "blocked", "suspicious", "unusual activity"
        ]):
            self.enter_conservative_mode()
            return self.config.MAX_BACKOFF
            
        return self._calculate_backoff(min(self.error_count, 3))
        
    def get_hourly_request_count(self) -> int:
        """Get number of requests made in the last hour."""
        hour_ago = time.time() - 3600
        return len([ts for ts in self.request_history if ts > hour_ago])
        
    def can_make_request(self) -> bool:
        """Check if we can make a request based on current limits."""
        return (
            self.get_hourly_request_count() < self.config.INSTAGRAM_REQUESTS_PER_HOUR and
            not self.in_conservative_mode
        )