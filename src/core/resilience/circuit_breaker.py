"""Circuit breaker pattern implementation for handling service failures."""

import asyncio
import time
from typing import Any, Callable, TypeVar
from functools import wraps

T = TypeVar('T')

class ServiceUnavailableError(Exception):
    """Raised when a service is unavailable due to too many failures."""
    pass

class CircuitBreaker:
    """
    Circuit breaker to prevent cascade failures by stopping operation attempts
    when a service is failing.
    """
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failures = 0
        self.last_failure_time = 0
        self.threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._is_open = False

    def is_open(self) -> bool:
        """Check if circuit breaker is open (service should not be called)."""
        if not self._is_open:
            return False
            
        # Check if enough time has passed to try again
        if time.time() - self.last_failure_time >= self.reset_timeout:
            self._is_open = False
            self.failures = 0
            return False
            
        return True

    def record_failure(self) -> None:
        """Record a failure and potentially open the circuit."""
        self.failures += 1
        self.last_failure_time = time.time()
        
        if self.failures >= self.threshold:
            self._is_open = True

    def record_success(self) -> None:
        """Record a success and reset the failure count."""
        self.failures = 0
        self._is_open = False

    async def call_service(self, service_func: Callable[..., T], *args, **kwargs) -> T:
        """
        Call a service function with circuit breaker protection.
        
        Args:
            service_func: Async function to call
            *args: Arguments for the service function
            **kwargs: Keyword arguments for the service function
            
        Returns:
            The result of the service function
            
        Raises:
            ServiceUnavailableError: If circuit breaker is open
        """
        if self.is_open():
            raise ServiceUnavailableError(
                f"Circuit breaker is open. Service unavailable for {self.reset_timeout}s"
            )
            
        try:
            result = await service_func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

def with_circuit_breaker(
    failure_threshold: int = 5,
    reset_timeout: int = 60
) -> Callable:
    """
    Decorator to add circuit breaker protection to a function.
    
    Args:
        failure_threshold: Number of failures before opening circuit
        reset_timeout: Seconds to wait before attempting to close circuit
        
    Returns:
        Decorated function with circuit breaker protection
    """
    breaker = CircuitBreaker(failure_threshold, reset_timeout)
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await breaker.call_service(func, *args, **kwargs)
        return wrapper
    return decorator
