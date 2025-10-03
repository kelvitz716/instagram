"""Service manager to handle service lifecycles."""

import asyncio
import logging
from typing import Dict, Type
from src.core.base_service import BaseService
from src.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

class ServiceManager:
    """Manages initialization and cleanup of bot services."""
    
    def __init__(self):
        self._services: Dict[str, BaseService] = {}
        self._initialized = False
    
    def register(self, name: str, service: BaseService) -> None:
        """Register a service with the manager."""
        if name in self._services:
            raise ConfigurationError(f"Service {name} already registered")
        self._services[name] = service
    
    async def initialize_all(self, ordered_names: list[str] = None) -> None:
        """
        Initialize all services in order.
        
        Args:
            ordered_names: Optional list of service names specifying initialization order.
                         Services not in the list will be initialized last in arbitrary order.
        """
        if self._initialized:
            return
            
        to_initialize = set(self._services.keys())
        
        # Initialize ordered services first
        if ordered_names:
            for name in ordered_names:
                if name in self._services and name in to_initialize:
                    await self._initialize_service(name)
                    to_initialize.remove(name)
        
        # Initialize remaining services
        for name in list(to_initialize):
            await self._initialize_service(name)
        
        self._initialized = True
    
    async def _initialize_service(self, name: str) -> None:
        """Initialize a single service with error handling."""
        service = self._services[name]
        try:
            logger.info(f"Initializing service: {name}")
            await service.initialize()
            logger.info(f"Service initialized: {name}")
        except Exception as e:
            logger.error(f"Failed to initialize service {name}: {e}")
            raise
    
    async def shutdown_all(self) -> None:
        """Shutdown all services in reverse initialization order."""
        if not self._initialized:
            return
            
        # Shutdown in reverse order
        for name in reversed(list(self._services.keys())):
            service = self._services[name]
            try:
                logger.info(f"Shutting down service: {name}")
                await service.shutdown()
                logger.info(f"Service shut down: {name}")
            except Exception as e:
                logger.error(f"Error shutting down service {name}: {e}")
    
    def get_service(self, name: str) -> BaseService:
        """Get a registered service by name."""
        if name not in self._services:
            raise ConfigurationError(f"Service {name} not found")
        return self._services[name]