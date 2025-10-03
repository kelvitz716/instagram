"""Base service class with common functionality."""

import asyncio
from abc import ABC, abstractmethod
from typing import Optional

class BaseService(ABC):
    """Base class for all services with lifecycle management."""
    
    def __init__(self):
        self._initialized = False
        self._shutdown = False
        self._tasks: set[asyncio.Task] = set()
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the service. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up service resources. Must be implemented by subclasses."""
        pass
    
    def create_task(self, coro, name: Optional[str] = None) -> asyncio.Task:
        """Create and track an asyncio task."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
    
    async def wait_tasks(self, timeout: Optional[float] = None) -> None:
        """Wait for all running tasks to complete."""
        if not self._tasks:
            return
            
        await asyncio.wait(
            self._tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED
        )
    
    def cancel_tasks(self) -> None:
        """Cancel all running tasks."""
        for task in self._tasks:
            task.cancel()
    
    @property
    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._initialized
    
    @property
    def is_shutdown(self) -> bool:
        """Check if service is shut down."""
        return self._shutdown