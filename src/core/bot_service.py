"""Enhanced Telegram bot implementation."""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, Optional

import structlog
from telegram import Update
from telegram.ext import Application, ContextTypes

from src.core.config import BotConfig
from src.core.base_service import BaseService
from src.core.service_manager import ServiceManager
from src.core.help_command import HelpCommandMixin
from src.core.session_commands import SessionCommands
from src.core.exceptions import InstagramBotError
from src.services.url_detection import URLDetectionService
from src.services.instagram_downloader import InstagramDownloader
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.session_storage import SessionStorageService

logger = structlog.get_logger(__name__)

class BotService(BaseService):
    """Main bot service implementation."""
    
    def __init__(self, config: BotConfig):
        """Initialize bot service with configuration."""
        super().__init__()
        self.config = config
        self.service_manager = ServiceManager()
        self.url_service = URLDetectionService()
        self._cache: Dict[str, Any] = {}
        
        # Register core services
        self._register_services()
        
        # Initialize application
        self.bot_app = None  # Will be initialized in start()
    
    def _register_services(self) -> None:
        """Register all required services."""
        # Core services
        database = DatabaseService(self.config.database)
        self.service_manager.register('database', database)
        
        # Session services
        session_storage = SessionStorageService(database, self.config.downloads_path)
        self.service_manager.register('session_storage', session_storage)
        
        # Content services    
        instagram = InstagramDownloader(self.config.instagram)
        self.service_manager.register('instagram', instagram)
        
        # Upload service with configuration
        upload_service = FileUploadService(self.config.upload)
        self.service_manager.register('uploader', upload_service)
    
    async def initialize(self) -> None:
        """Initialize all services in proper order."""
        if self._initialized:
            return
            
        try:
            # Initialize core services first
            await self.service_manager.initialize_all([
                'database',
                'session_storage',
                'instagram',
                'uploader'
            ])
            
            self._initialized = True
            logger.info("Bot services initialized successfully")
            
        except Exception as e:
            logger.error("Failed to initialize bot services", error=str(e))
            raise InstagramBotError("Service initialization failed") from e
    
    async def shutdown(self) -> None:
        """Shutdown all services gracefully."""
        if self._shutdown:
            return
            
        try:
            await self.service_manager.shutdown_all()
            self._shutdown = True
            logger.info("Bot services shut down successfully")
            
        except Exception as e:
            logger.error("Error during service shutdown", error=str(e))
            raise InstagramBotError("Service shutdown failed") from e