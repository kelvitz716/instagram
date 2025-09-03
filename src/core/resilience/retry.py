"""Retry pattern implementation with configurable backoff strategies."""

import asyncio
import random
from functools import wraps
from typing import TypeVar, Callable, Type, Union, List, Optional

T = TypeVar('T')

class RetryConfig:
    """Configuration for retry behavior."""
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        exceptions: Optional[List[Type[Exception]]] = None
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter
        self.exceptions = exceptions or [Exception]

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given retry attempt."""
        delay = min(
            self.initial_delay * (self.backoff_factor ** attempt),
            self.max_delay
        )
        
        if self.jitter:
            # Add random jitter between 0-30% of delay
            jitter_amount = delay * random.uniform(0, 0.3)
            delay += jitter_amount
            
        return delay

def with_retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    exceptions: Optional[List[Type[Exception]]] = None
) -> Callable:
    """
    Decorator to add retry behavior to a function.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        backoff_factor: Factor to multiply delay by after each retry
        jitter: Whether to add random jitter to delays
        exceptions: List of exceptions to retry on
        
    Returns:
        Decorated function with retry behavior
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        max_delay=max_delay,
        backoff_factor=backoff_factor,
        jitter=jitter,
        exceptions=exceptions
    )
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None
            
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                    
                except tuple(config.exceptions) as e:
                    last_exception = e
                    
                    if attempt == config.max_retries:
                        raise
                        
                    delay = config.calculate_delay(attempt)
                    await asyncio.sleep(delay)
                    
            raise last_exception  # Should never reach here
            
        return wrapper
    return decorator
