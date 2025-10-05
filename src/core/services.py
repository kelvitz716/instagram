import logging
from dataclasses import dataclass
from typing import Optional
from .config import BotConfig
from typing import TYPE_CHECKING

# Import service types
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.database import DatabaseService
from src.services.progress import ProgressTracker
from src.services.instagram_rate_limiter import InstagramRateLimiter
from src.services.session_storage import SessionStorageService
from src.services.cleanup import CleanupService
    
from src.services.database import DatabaseService

@dataclass
class BotServices:
    """Container for all bot services"""
    config: BotConfig
    bot_api_uploader: Optional["BotAPIUploader"] = None
    telethon_uploader: Optional["TelethonUploader"] = None
    instagram_service: Optional["InstagramDownloader"] = None
    database_service: Optional["DatabaseService"] = None
    progress_tracker: Optional["ProgressTracker"] = None
    rate_limiter: Optional["InstagramRateLimiter"] = None
    session_storage: Optional["SessionStorageService"] = None
    cleanup_service: Optional["CleanupService"] = None
    
    @classmethod
    def create(cls, config: BotConfig) -> "BotServices":
        """Factory method to create and initialize all services"""
        services = cls(config=config)
        
        # Create database service first
        services.database_service = DatabaseService(config.database)
        
        # Create session storage service next since many services depend on it
        from src.services.session_storage import SessionStorageService
        services.session_storage = SessionStorageService(
            services.database_service, 
            config.downloads_path
        )
        
        # Create rate limiter before Instagram service
        from src.services.instagram_rate_limiter import InstagramRateLimiter
        services.rate_limiter = InstagramRateLimiter('config/rate_limiting.conf')
        
        # Create progress tracker
        from src.services.progress import ProgressTracker
        services.progress_tracker = ProgressTracker()
        
        # Create Instagram service 
        from src.services.instagram_downloader import InstagramDownloader
        services.instagram_service = InstagramDownloader(config=config.instagram)
        services.instagram_service.rate_limiter = services.rate_limiter  # Set after construction
        services.instagram_service.session_storage = services.session_storage  # Set after construction
        
        # Create upload services based on file size limits
        from src.services.bot_api_uploader import BotAPIUploader
        from src.services.telethon_uploader import TelethonUploader
        
        # Bot API uploader for files ≤50MB
        services.bot_api_uploader = BotAPIUploader(
            bot_token=config.telegram.bot_token,
            chat_id=config.telegram.target_chat_id
        )
        
        # Telethon uploader for files >50MB
        services.telethon_uploader = TelethonUploader(
            client=None,  # Will be set during initialization
            chat_id=config.telegram.target_chat_id,
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash
        )
        
        # Create cleanup service
        from src.services.cleanup import CleanupService
        services.cleanup_service = CleanupService(
            downloads_path=str(config.downloads_path)  # Convert Path to str
        )
        
        return services
    
    def get(self, service_type):
        """Get a service by its type."""
        if service_type == CleanupService:
            return self.cleanup_service
        elif service_type == DatabaseService:
            return self.database_service
        elif service_type == InstagramDownloader:
            return self.instagram_service
        elif service_type == BotAPIUploader:
            return self.bot_api_uploader
        elif service_type == TelethonUploader:
            return self.telethon_uploader
        elif service_type == ProgressTracker:
            return self.progress_tracker
        elif service_type == SessionStorageService:
            return self.session_storage
        return None
    
    async def start_all(self):
        """Start all services."""
        # Initialize any async services if needed
        pass
    
    async def stop_all(self):
        """Stop all services."""
        # Cleanup and stop any services that need it
        pass
        
    async def initialize(self):
        """Initialize all services in dependency order with proper error handling"""
        try:
            # Initialize database first as other services depend on it
            if self.database_service:
                await self.database_service.initialize()
            
            # Initialize session storage next
            if self.session_storage:
                await self.session_storage.initialize()
            
            # Initialize rate limiter
            if self.rate_limiter:
                await self.rate_limiter.initialize()
            
            # Initialize progress tracker
            if self.progress_tracker:
                await self.progress_tracker.initialize()
            
            # Initialize services that depend on others
            if self.instagram_service:
                await self.instagram_service.initialize()
                
            if self.file_service:
                await self.file_service.initialize()
            
            if self.cleanup_service:
                await self.cleanup_service.initialize()
                
        except Exception as e:
            # Log the error and try to cleanup
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to initialize services: {e}")
            await self.cleanup()
            raise
    
    async def cleanup(self):
        """Cleanup all services in reverse initialization order"""
        logger = logging.getLogger(__name__)
        
        # Cleanup in reverse order of initialization
        services = [
            self.cleanup_service,
            self.file_service,
            self.instagram_service,
            self.progress_tracker,
            self.rate_limiter,
            self.session_storage,
            self.database_service
        ]
        
        for service in services:
            if service:
                try:
                    await service.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up service {service.__class__.__name__}: {e}")
