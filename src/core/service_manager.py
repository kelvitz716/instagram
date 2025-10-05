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
        """Initialize the service manager."""
        self._services: Dict[str, BaseService] = {}
        self._initialized = False
        self._startup_order = [
            'database',
            'session_storage',
            'telegram',
            'instagram',
            'uploader'
        ]
    
    def register(self, name: str, service: BaseService) -> None:
        """
        Register a service with the manager.
        
        Args:
            name: Unique identifier for the service
            service: Service instance implementing BaseService
        
        Raises:
            ConfigurationError: If service name already registered
        """
        if name in self._services:
            raise ConfigurationError(f"Service {name} already registered")
        self._services[name] = service
    
    async def initialize_all(self) -> None:
        """
        Initialize all services in predefined order.
        
        The initialization order is defined by self._startup_order.
        Services not in the startup order are initialized last.
        
        Raises:
            ConfigurationError: If a required service is missing
        """
        if self._initialized:
            return
            
        # Validate required services
        missing = [name for name in self._startup_order 
                  if name not in self._services]
        if missing:
            raise ConfigurationError(f"Required services missing: {', '.join(missing)}")
            
        # Initialize ordered services first
        for name in self._startup_order:
            if name in self._services:
                await self._initialize_service(name)
        
        # Initialize any remaining services
        remaining = set(self._services.keys()) - set(self._startup_order)
        for name in remaining:
            await self._initialize_service(name)
        
        self._initialized = True
    
    async def _initialize_service(self, name: str) -> None:
        """Initialize a single service by name."""
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