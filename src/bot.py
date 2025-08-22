#!/usr/bin/env python3
"""
Enhanced Telegram Bot with service-based architecture and optimized performance.
"""
import asyncio
import logging
import structlog
from pathlib import Path
from typing import Optional, Dict, Any
from functools import lru_cache
from rich.console import Console

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient

from src.core.config import BotConfig
from src.core.services import BotServices
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.progress import ProgressTracker

# Optimize logging configuration
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)
console = Console()
BOT_VERSION = "2.0.0"

class EnhancedTelegramBot:
    """Enhanced Telegram bot with optimized service architecture."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.services = BotServices.create(config)
        self._setup_directories()
        self._cache: Dict[str, Any] = {}
        
    def _setup_directories(self) -> None:
        """Setup required directories with error handling."""
        try:
            for path in [self.config.downloads_path, self.config.uploads_path, self.config.temp_path]:
                path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create directories", error=str(e))
            raise
            
    @lru_cache(maxsize=1)
    def _get_uploader(self, file_size: int) -> str:
        """Cached decision for uploader selection based on file size."""
        return 'telethon' if file_size > self.config.upload.large_file_threshold else 'bot_api'

    async def initialize(self) -> None:
        """Initialize bot services with optimized async startup."""
        try:
            # Initialize core services in parallel
            await asyncio.gather(
                self._initialize_database(),
                self._initialize_telegram(),
                self._initialize_uploaders()
            )
            
            logger.info("Bot initialized successfully", version=BOT_VERSION)
            
        except Exception as e:
            logger.error("Failed to initialize bot", error=str(e))
            raise

    async def _initialize_database(self) -> None:
        """Initialize database with connection pooling."""
        self.services.database_service = DatabaseService(self.config.database)
        await self.services.database_service.initialize()

    async def _initialize_telegram(self) -> None:
        """Initialize Telegram clients with optimized settings."""
        # Initialize bot application with optimized settings
        self.bot_app = Application.builder().token(
            self.config.telegram.bot_token
        ).connect_timeout(
            self.config.telegram.connection_timeout
        ).read_timeout(
            self.config.telegram.read_timeout
        ).write_timeout(
            self.config.telegram.bot_api_timeout
        ).pool_timeout(
            self.config.telegram.connection_timeout
        ).build()
        
        self._setup_handlers()

        # Initialize Telethon with connection pooling
        self.telethon_client = TelegramClient(
            self.config.telegram.session_name,
            self.config.telegram.api_id,
            self.config.telegram.api_hash,
            connection_retries=self.config.telegram.network_retry_attempts,
            retry_delay=self.config.telegram.flood_control_base_delay,
            auto_reconnect=True
        )
        await self.telethon_client.start()

    async def _initialize_uploaders(self) -> None:
        """Initialize upload services with optimized configuration."""
        self.services.file_service = FileUploadService(self.config.upload)
        
        # Configure uploaders with optimal settings
        bot_api_uploader = BotAPIUploader(
            self.config.telegram.bot_token,
            self.config.telegram.target_chat_id,
        )
        
        telethon_uploader = TelethonUploader(
            self.telethon_client,
            self.config.telegram.target_chat_id,
            self.config.telegram.api_id,
            self.config.telegram.api_hash
        )
        
        # Register uploaders
        self.services.file_service.register_uploader('bot_api', bot_api_uploader)
        self.services.file_service.register_uploader('telethon', telethon_uploader)

    def _setup_handlers(self) -> None:
        """Set up command handlers with rate limiting."""
        handlers = [
            ("start", self.handle_start),
            ("stats", self.handle_stats),
            ("instagram", self.handle_download_instagram)
        ]
        
        for command, handler in handlers:
            self.bot_app.add_handler(CommandHandler(command, handler))

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command with minimal processing."""
        await update.message.reply_text(
            f"👋 Welcome to Instagram Downloader Bot v{BOT_VERSION}\n\n"
            "Available commands:\n"
            "/instagram <url> - Download Instagram post, carousel, or reel\n"
            "/stats - Show bot statistics\n\n"
            "Simply paste the URL of any Instagram post, carousel, or reel to download it."
        )

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command with cached statistics."""
        stats = await self.services.database_service.get_statistics()
        await update.message.reply_text(
            "📊 Bot Statistics:\n\n"
            f"Total Downloads: {stats.get('total_downloads', 0)}\n"
            f"Successful: {stats.get('successful_downloads', 0)}\n"
            f"Failed: {stats.get('failed_downloads', 0)}\n"
            f"Total Uploads: {stats.get('total_uploads', 0)}\n"
            f"Successful: {stats.get('successful_uploads', 0)}\n"
            f"Failed: {stats.get('failed_uploads', 0)}"
        )

    async def handle_download_instagram(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /instagram command with optimized processing."""
        if not context.args:
            await update.message.reply_text(
                "Please provide an Instagram URL.\n"
                "Usage: /instagram <url>"
            )
            return

        url = context.args[0]
        status_message = await update.message.reply_text(
            "⏬ Starting download..."
        )

        try:
            # Optimized download process
            files = await self.services.instagram_service.download_post(url)
            if not files:
                await status_message.edit_text("❌ Failed to download content")
                return

            await status_message.edit_text(
                f"✅ Downloaded {len(files)} files\n"
                "📤 Starting upload..."
            )

            # Process files in batches with concurrent uploads
            successful = 0
            batch_size = self.config.upload.batch_size
            
            for i in range(0, len(files), batch_size):
                batch = files[i:i + batch_size]
                upload_tasks = []
                
                for file in batch:
                    file_size = file.stat().st_size
                    uploader = self._get_uploader(file_size)
                    upload_tasks.append(self.services.file_service.upload_file(file, uploader))
                
                # Process batch concurrently
                results = await asyncio.gather(*upload_tasks, return_exceptions=True)
                
                # Count successes and log operations
                for file, result in zip(batch, results):
                    success = isinstance(result, bool) and result
                    await self.services.database_service.log_file_operation(
                        str(file),
                        file.stat().st_size,
                        'upload',
                        success,
                        None if success else str(result) if not isinstance(result, bool) else "Upload failed"
                    )
                    if success:
                        successful += 1

            # Update final status
            await status_message.edit_text(
                f"✅ Process complete!\n"
                f"📥 Downloaded: {len(files)} files\n"
                f"📤 Uploaded: {successful}/{len(files)} files"
            )

        except Exception as e:
            logger.error("Error processing Instagram URL", url=url, error=str(e))
            await status_message.edit_text(f"❌ Error: {str(e)}")
            await self.services.database_service.log_file_operation(
                url, 0, 'download', False, str(e)
            )

    async def shutdown(self) -> None:
        """Shutdown the bot with optimized cleanup."""
        try:
            shutdown_tasks = []
            
            # Stop bot application
            if self.bot_app:
                if self.bot_app.updater:
                    shutdown_tasks.append(self.bot_app.updater.stop())
                shutdown_tasks.append(self.bot_app.stop())
                shutdown_tasks.append(self.bot_app.shutdown())
            
            # Disconnect Telethon
            if self.telethon_client:
                shutdown_tasks.append(self.telethon_client.disconnect())
            
            # Close database
            if self.services.database_service:
                shutdown_tasks.append(self.services.database_service.close())
            
            # Run all cleanup tasks concurrently
            await asyncio.gather(*shutdown_tasks)
            logger.info("Bot shutdown complete")
            
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))

async def main() -> None:
    """Initialize and run the bot with optimized startup."""
    from src.core.load_config import load_configuration
    
    config = load_configuration()
    bot = EnhancedTelegramBot(config)
    
    try:
        await bot.initialize()
        await bot.bot_app.initialize()
        await bot.bot_app.start()
        await bot.bot_app.updater.start_polling()
        
        # Keep the bot running until interrupted
        stop_event = asyncio.Event()
        await stop_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await bot.shutdown()

def run_bot() -> None:
    """Run the bot with proper event loop and error handling."""
    try:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    run_bot()
