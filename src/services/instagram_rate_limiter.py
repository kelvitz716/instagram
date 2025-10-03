import time
import random
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional

class InstagramRateLimiter:
    def __init__(self, config_path: str = 'config/rate_limiting.conf'):
        self.last_request_time: float = 0
        self.request_count: int = 0
        self.error_count: int = 0
        self.current_backoff: float = 10
        self.in_conservative_mode: bool = False
        self.conservative_mode_start: Optional[datetime] = None
        self.session_request_count: int = 0
        self.session_start_time: datetime = datetime.now()
        self.load_config(config_path)
        
        # Request history for pattern detection
        self.request_history: Dict[float, str] = {}
        
    def load_config(self, config_path: str):
        # Load configuration from file
        # For now using default values, implement config loading as needed
        self.requests_per_hour = 100
        self.min_request_interval = 6
        self.batch_delay = 30
        self.max_backoff = 1800
        self.backoff_multiplier = 2
        self.backoff_jitter = 0.1
        
    def add_jitter(self, delay: float) -> float:
        """Add random jitter to delay to avoid synchronized requests."""
        jitter = delay * self.backoff_jitter
        return delay + random.uniform(-jitter, jitter)
    
    def should_rotate_session(self) -> bool:
        """Check if we should rotate the session based on usage."""
        session_age = datetime.now() - self.session_start_time
        return (session_age.total_seconds() >= 3600 or 
                self.session_request_count >= 50)
    
    def enter_conservative_mode(self):
        """Enter conservative mode after detecting potential issues."""
        self.in_conservative_mode = True
        self.conservative_mode_start = datetime.now()
        logging.warning("Entering conservative mode for 30 minutes")
        
    def exit_conservative_mode(self):
        """Exit conservative mode if conditions are met."""
        if self.conservative_mode_start:
            elapsed = datetime.now() - self.conservative_mode_start
            if elapsed.total_seconds() >= 1800:  # 30 minutes
                self.in_conservative_mode = False
                self.error_count = 0
                logging.info("Exiting conservative mode")
    
    async def wait_for_request(self, request_type: str = 'normal') -> None:
        """Smart wait before making a request to Instagram."""
        current_time = time.time()
        
        # Check and potentially exit conservative mode
        self.exit_conservative_mode()
        
        # Calculate base delay
        time_since_last = current_time - self.last_request_time
        base_delay = max(0, self.min_request_interval - time_since_last)
        
        # Adjust delay based on conditions
        if self.in_conservative_mode:
            base_delay *= 2  # Double the delay in conservative mode
        
        if request_type == 'batch':
            base_delay = max(base_delay, self.batch_delay)
        
        # Add jitter for more natural timing
        delay = self.add_jitter(base_delay)
        
        # Wait the calculated time
        if delay > 0:
            await asyncio.sleep(delay)
        
        # Update tracking
        self.last_request_time = time.time()
        self.request_count += 1
        self.session_request_count += 1
        self.request_history[time.time()] = request_type
        
        # Clean old history
        self._clean_history()
    
    def _clean_history(self):
        """Clean request history older than 1 hour."""
        threshold = time.time() - 3600
        self.request_history = {
            ts: rt for ts, rt in self.request_history.items() 
            if ts > threshold
        }
    
    def handle_error(self, error_type: str):
        """Handle different types of errors with appropriate backoff."""
        self.error_count += 1
        
        if error_type == 'rate_limit':
            self.current_backoff = min(
                self.current_backoff * self.backoff_multiplier,
                self.max_backoff
            )
            if self.error_count >= 5:
                self.enter_conservative_mode()
        
        elif error_type == 'suspicious_activity':
            self.enter_conservative_mode()
            self.current_backoff = self.max_backoff
        
    def get_hourly_request_count(self) -> int:
        """Get number of requests made in the last hour."""
        hour_ago = time.time() - 3600
        return len([ts for ts in self.request_history if ts > hour_ago])
    
    def can_make_request(self) -> bool:
        """Check if we can make a request based on current limits."""
        return (self.get_hourly_request_count() < self.requests_per_hour and
                not self.in_conservative_mode)