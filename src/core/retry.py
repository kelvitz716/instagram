import asyncio
import logging
from functools import wraps
from typing import Type, Union, Optional, List, Callable, Any

logger = logging.getLogger(__name__)

def with_retry(max_retries: int = 3):
    """Decorator for retrying operations with exponential backoff."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Max retries ({max_retries}) exceeded", exc_info=True)
                        raise
                    wait_time = (2 ** attempt) + (asyncio.get_event_loop().time() % 1)
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time:.1f}s: {str(e)}")
                    await asyncio.sleep(wait_time)
            return None
        return wrapper
    return decorator

class MaxRetriesExceeded(Exception):
    """Raised when maximum retries are exceeded"""
    pass

class RetryableOperation:
    """
    Decorator for operations that need retry logic with exponential backoff
    
    Usage:
        @RetryableOperation(max_retries=3, exceptions=[NetworkError, TimeoutError])
        async def some_operation():
            # Operation that might need retrying
    """
    
    def __init__(
        self, 
        max_retries: int = 3,
        backoff_factor: float = 1.5,
        exceptions: Optional[List[Type[Exception]]] = None,
        should_retry: Optional[Callable[[Exception], bool]] = None,
        on_retry: Optional[Callable[[int, Exception], Any]] = None
    ):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions or [Exception]
        self.should_retry = should_retry
        self.on_retry = on_retry
    
    def __call__(self, func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(self.max_retries):
                try:
                    return await func(*args, **kwargs)
                except tuple(self.exceptions) as e:
                    last_exception = e
                    
                    # Check if we should retry this error
                    if self.should_retry and not self.should_retry(e):
                        raise
                    
                    # Last attempt - don't wait, just raise
                    if attempt == self.max_retries - 1:
                        raise MaxRetriesExceeded(
                            f"Operation failed after {self.max_retries} attempts"
                        ) from last_exception
                    
                    # Calculate delay with exponential backoff
                    delay = (2 ** attempt) * self.backoff_factor
                    
                    # Add some jitter to prevent thundering herd
                    jitter = delay * 0.1
                    delay += asyncio.get_running_loop().time() % jitter
                    
                    logger.warning(
                        f"Operation failed (attempt {attempt + 1}/{self.max_retries}), "
                        f"retrying in {delay:.1f}s",
                        exc_info=last_exception
                    )
                    
                    # Call the retry callback if provided
                    if self.on_retry:
                        await self.on_retry(attempt, last_exception)
                    
                    await asyncio.sleep(delay)
            
            # This shouldn't be reached, but just in case
            raise MaxRetriesExceeded(
                f"Operation failed after {self.max_retries} attempts"
            ) from last_exception
        
        return wrapper
