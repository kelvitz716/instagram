"""Rate limiting implementation using token bucket algorithm"""
import asyncio
import time
from typing import Dict, Optional

class RateLimiter:
    """Token bucket rate limiter to prevent hitting API rate limits"""

    def __init__(self, tokens_per_second: float, burst_limit: int):
        self.tokens_per_second = tokens_per_second
        self.burst_limit = burst_limit
        self.tokens = burst_limit  # Start with full bucket
        self.last_update = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """Acquire a token, waiting if none are available"""
        async with self.lock:
            while True:
                now = time.monotonic()
                time_passed = now - self.last_update
                self.tokens = min(
                    self.burst_limit,
                    self.tokens + time_passed * self.tokens_per_second
                )
                
                if self.tokens >= 1:
                    self.tokens -= 1
                    self.last_update = now
                    break
                else:
                    # Calculate time needed for at least one token
                    wait_time = (1 - self.tokens) / self.tokens_per_second
                    await asyncio.sleep(wait_time)

class RateLimiterRegistry:
    """Registry of rate limiters for different methods/resources"""

    def __init__(self):
        self._limiters: Dict[str, RateLimiter] = {}

    def get_limiter(self, name: str, tokens_per_second: float = 0.2, burst_limit: int = 2) -> RateLimiter:
        """Get or create a rate limiter for the given name"""
        if name not in self._limiters:
            self._limiters[name] = RateLimiter(tokens_per_second, burst_limit)
        return self._limiters[name]
