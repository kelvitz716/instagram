"""Request tracking and correlation system."""

import time
import uuid
import asyncio
import structlog
from typing import Dict, Optional, Any
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime

logger = structlog.get_logger(__name__)

@dataclass
class Request:
    """Information about a request being tracked."""
    id: str
    start_time: float
    user_id: Optional[int]
    chat_id: Optional[int]
    operation: str
    metadata: Dict[str, Any]
    parent_id: Optional[str] = None

class RequestTracker:
    """
    Tracks requests through the system.
    
    Features:
    - Request correlation
    - Timing and duration tracking
    - Parent-child request relationships
    - Request context propagation
    """
    
    def __init__(self, metrics_collector = None):
        self.metrics = metrics_collector
        self.active_requests: Dict[str, Request] = {}
        
    def generate_request_id(self) -> str:
        """Generate a unique request ID."""
        return str(uuid.uuid4())
    
    @asynccontextmanager
    async def track_request(
        self,
        operation: str,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        parent_id: Optional[str] = None,
        **metadata: Any
    ):
        """
        Context manager for tracking a request.
        
        Args:
            operation: Type of operation being performed
            user_id: ID of the user making the request
            chat_id: ID of the chat where the request originated
            parent_id: ID of the parent request if this is a sub-request
            **metadata: Additional metadata about the request
        """
        request_id = self.generate_request_id()
        request = Request(
            id=request_id,
            start_time=time.time(),
            user_id=user_id,
            chat_id=chat_id,
            operation=operation,
            metadata=metadata,
            parent_id=parent_id
        )
        
        # Store the request
        self.active_requests[request_id] = request
        
        # Set up logging context
        log = logger.bind(
            request_id=request_id,
            operation=operation,
            user_id=user_id,
            chat_id=chat_id,
            parent_id=parent_id
        )
        
        try:
            # Log request start
            log.info(
                "Request started",
                metadata=metadata
            )
            
            # Yield the request ID and logger
            yield request_id, log
            
            # Calculate duration
            duration = time.time() - request.start_time
            
            # Log request completion
            log.info(
                "Request completed",
                duration=duration,
                metadata=metadata
            )
            
            # Update metrics if available
            if self.metrics:
                self.metrics.observe_request_duration(operation, duration)
                
        except Exception as e:
            # Calculate duration even for failed requests
            duration = time.time() - request.start_time
            
            # Log request failure
            log.error(
                "Request failed",
                error=str(e),
                duration=duration,
                metadata=metadata,
                exc_info=True
            )
            
            # Update error metrics if available
            if self.metrics:
                self.metrics.record_request_error(operation)
            
            raise
            
        finally:
            # Clean up
            self.active_requests.pop(request_id, None)
    
    def get_request(self, request_id: str) -> Optional[Request]:
        """Get information about an active request."""
        return self.active_requests.get(request_id)
    
    def get_child_requests(self, parent_id: str) -> Dict[str, Request]:
        """Get all child requests of a given parent request."""
        return {
            rid: req for rid, req in self.active_requests.items()
            if req.parent_id == parent_id
        }
    
    def get_request_duration(self, request_id: str) -> Optional[float]:
        """Get the current duration of an active request."""
        request = self.active_requests.get(request_id)
        if request:
            return time.time() - request.start_time
        return None