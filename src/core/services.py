from dataclasses import dataclass
from typing import Optional
from .config import BotConfig

@dataclass
class BotServices:
    """Container for all bot services"""
    config: BotConfig
    file_service: Optional["FileUploadService"] = None
    instagram_service: Optional["InstagramDownloader"] = None
    database_service: Optional["DatabaseService"] = None
    progress_tracker: Optional["ProgressTracker"] = None
    rate_limiter: Optional["TelegramRateLimiter"] = None
    
    @classmethod
    def create(cls, config: BotConfig) -> "BotServices":
        """Factory method to create and initialize all services"""
        return cls(
            config=config,
            file_service=None,  # Will be initialized later
            instagram_service=None,  # Will be initialized later
            database_service=None,  # Will be initialized later
            progress_tracker=None,  # Will be initialized later
            rate_limiter=None  # Will be initialized later
        )
    
    async def initialize(self):
        """Initialize all services"""
        # This will be implemented once we have all service classes
        pass
    
    async def cleanup(self):
        """Cleanup all services"""
        # This will be implemented once we have all service classes
        pass
