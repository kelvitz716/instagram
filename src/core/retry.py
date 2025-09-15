import asyncio
import logging
from functools import wraps
from typing import Type, Union, Optional, List, Callable, Any

logger = logging.getLogger(__name__)

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
                    # Remove status_message from kwargs if it's not a parameter of the function
                    import inspect
                    sig = inspect.signature(func)
                    if 'status_message' not in sig.parameters and 'status_message' in kwargs:
                        status_message = kwargs.pop('status_message')
                        # Pass the status_message back if there's a retry callback
                        if self.on_retry:
                            kwargs['_status_message'] = status_message
                    
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
                    
                    # Call the retry callback if provided, checking for status_message
                    if self.on_retry:
                        # Use the cached status_message if available
                        retry_kwargs = {}
                        if '_status_message' in kwargs:
                            retry_kwargs['status_message'] = kwargs['_status_message']
                        await self.on_retry(attempt, last_exception, **retry_kwargs)
                    
                    await asyncio.sleep(delay)
            
            # This shouldn't be reached, but just in case
            raise MaxRetriesExceeded(
                f"Operation failed after {self.max_retries} attempts"
            ) from last_exception
        
        return wrapper
