import time
import random
from functools import wraps
import asyncio
from typing import Any, Callable

class SmartBackoff:
    def __init__(self):
        self.initial_delay = 10
        self.max_delay = 1800  # 30 minutes
        self.multiplier = 2
        self.jitter = 0.1
        
    def calculate_delay(self, attempts: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        delay = min(
            self.initial_delay * (self.multiplier ** attempts),
            self.max_delay
        )
        jitter_amount = delay * self.jitter
        return delay + random.uniform(-jitter_amount, jitter_amount)

def with_smart_retry(max_attempts: int = 3):
    """Decorator for implementing smart retry logic."""
    def decorator(func: Callable) -> Callable:
        backoff = SmartBackoff()
        
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    # Don't retry on certain errors
                    if "blocked" in str(e).lower() or "not found" in str(e).lower():
                        raise
                    
                    # Calculate and apply backoff
                    if attempt < max_attempts - 1:
                        delay = backoff.calculate_delay(attempt)
                        await asyncio.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator

# Example usage in your downloader:
@with_smart_retry(max_attempts=3)
async def download_media(self, url: str) -> str:
    """Download media with smart retry logic."""
    await self.rate_limiter.wait_for_request()
    # Your existing download logic here