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
        """Initialize bot services sequentially."""
        try:
            # Initialize database first as other services might need it
            await self._initialize_database()
            
            # Initialize components sequentially to avoid race conditions
            await self._initialize_database()
            await self._initialize_telegram()
            await self._initialize_uploaders()
            self._initialize_instagram()  # This one's sync as it just sets up instances
            
            # Set up instagram service in BotServices
            self.services.instagram_service = self.instagram_downloader
            
            logger.info("Bot initialized successfully", version=BOT_VERSION)
            
        except Exception as e:
            logger.error("Failed to initialize bot", error=str(e))
            raise
            
    def _initialize_instagram(self) -> None:
        """Initialize Instagram downloader and cleanup service."""
        downloads_path = self.config.downloads_path
        self.instagram_downloader = InstagramDownloader(
            self.config.instagram,
            downloads_path=downloads_path
        )
        
        # Initialize cleanup service
        from .services.cleanup import CleanupService
        self.cleanup_service = CleanupService(downloads_path)
        
    def _schedule_cleanup(self) -> None:
        """Schedule periodic cleanup of downloads directory"""
        async def scheduled_cleanup():
            try:
                dirs_removed, bytes_freed = self.cleanup_service.cleanup_old_directories()
                if dirs_removed > 0:
                    logger.info(f"Cleanup: Removed {dirs_removed} directories, freed {bytes_freed/1024/1024:.2f} MB")
            except Exception as e:
                logger.error(f"Scheduled cleanup failed: {e}")
        
        self.bot_app.job_queue.run_repeating(scheduled_cleanup, interval=24*60*60)

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

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle messages containing Instagram URLs."""
        if not update.message or not update.message.text:
            return
        
        import re
        
        # Clean and standardize URL
        url = update.message.text.strip()
        url = url.split('?')[0].rstrip('/')  # Remove query params and trailing slash
        
        # Define URL patterns for different Instagram content types
        patterns = {
            'post': r'https?://(?:www\.)?instagram\.com/p/[\w-]+',
            'reel': r'https?://(?:www\.)?instagram\.com/reel/[\w-]+',
            'story': r'https?://(?:www\.)?instagram\.com/stories/[\w\.]+',
            'highlight': r'https?://(?:www\.)?instagram\.com/stories/highlights/\d+'
        }
        
        # Check if URL matches any pattern
        for content_type, pattern in patterns.items():
            if re.match(pattern, url):
                logger.info(f"Processing {content_type} URL: {url}")
                await self._process_download(update, url)
                return

    def _setup_handlers(self) -> None:
        """Set up command handlers and message handlers."""
        from telegram.ext import MessageHandler, filters
        
        # Register command handlers first
        handlers = [
            ("start", self.handle_start),
            ("stats", self.handle_stats),
            ("instagram", self.handle_download_instagram)
        ]
        
        # Add command handlers
        for command, handler in handlers:
            self.bot_app.add_handler(CommandHandler(command, handler))
            
        # Add message handler for Instagram URLs with higher priority
        self.bot_app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.Regex(r'https?://(?:www\.)?(?:instagram\.com|instagr\.am)/\S+'),
                self.handle_message
            ),
            group=1
        )

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command with minimal processing."""
        await update.message.reply_text(
            f"👋 Welcome to Instagram Downloader Bot v{BOT_VERSION}\n\n"
            "Available commands:\n"
            "/instagram <url> - Download any Instagram content using URL\n"
            "/stats - Show bot statistics\n\n"
            "Supports:\n"
            "• Posts\n"
            "• Carousels\n"
            "• Reels\n"
            "• Stories (URL format: https://instagram.com/stories/username)\n"
            "• Highlights (URL format: https://instagram.com/stories/highlights/highlight_id)\n\n"
            "Simply paste any Instagram URL to download its content.\n"
            "Note: Story and highlight downloads require you to be logged into Instagram in Firefox."
        )

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command with cached statistics."""
        stats = await self.services.database_service.get_statistics()
        
        # Get storage stats
        storage_stats = self.cleanup_service.get_storage_stats()
        
        await update.message.reply_text(
            "📊 Bot Statistics:\n\n"
            f"Downloads:\n"
            f"• Total Attempts: {stats.get('total_downloads', 0)}\n"
            f"• Successful: {stats.get('successful_downloads', 0)}\n"
            f"• Failed: {stats.get('failed_downloads', 0)}\n\n"
            f"Files:\n"
            f"• Total Downloaded: {stats.get('total_files_downloaded', 0)}\n"
            f"• Successfully Uploaded: {stats.get('successful_file_uploads', 0)}\n"
            f"• Total Data: {stats.get('total_bytes_downloaded', 0)/1024/1024:.1f} MB\n\n"
            f"Storage:\n"
            f"• Current Size: {storage_stats.get('total_size_mb', 0):.1f} MB\n"
            f"• Total Directories: {storage_stats.get('total_directories', 0)}\n"
            f"• Old Directories: {storage_stats.get('old_directories', 0)}"
        )

    async def _process_download(self, update: Update, url: str) -> None:
        """Unified method for processing downloads from any Instagram content"""
        status_message = None
        try:
            status_message = await update.message.reply_text(
                "⏬ Starting download..."
            )
            
            # Try to detect content type first
            content_type, identifier = await self.instagram_downloader.detect_content_type(url)
            
            # Update status message with detected content type
            content_type_msg = {
                "post": "post",
                "reel": "reel",
                "story": "story",
                "highlight": "highlight",
                "unknown": "content"
            }.get(content_type, "content")
            
            await status_message.edit_text(
                f"⏬ Downloading {content_type_msg}..."
            )
            
            # Download content using unified method
            downloaded_files = await self.instagram_downloader.download_content(url)
            if not downloaded_files:
                await status_message.edit_text("❌ Failed to download content")
                return
                
            await status_message.edit_text(
                f"✅ Downloaded {len(downloaded_files)} files\n"
                "📤 Starting upload..."
            )
            
            # Extract metadata for the first file (they'll share the same metadata)
            metadata = await self.instagram_downloader._extract_metadata(downloaded_files[0])
            
            # Build caption based on content type
            caption = ""
            if metadata.get('username'):
                caption += f"👤 @{metadata['username']}\n\n"
            if metadata.get('caption'):
                caption += f"{metadata['caption']}\n\n"
            caption += f"📱 Total media: {len(downloaded_files)}\n"
            if metadata.get('likes'):
                caption += f"❤️ {metadata['likes']:,} likes\n"
            if metadata.get('comments'):
                caption += f"💬 {metadata['comments']:,} comments\n"
            if metadata.get('url'):
                caption += f"\n🔗 {metadata['url']}"
            
            # Process files in batches with concurrent uploads
            successful = 0
            batch_size = self.config.upload.batch_size
            media_count = len(downloaded_files)
            
            for i in range(0, len(downloaded_files), batch_size):
                batch = downloaded_files[i:i + batch_size]
                upload_tasks = []
                
                for idx, file in enumerate(batch, start=i+1):
                    file_size = file.stat().st_size
                    uploader = self._get_uploader(file_size)
                    file_caption = f"{caption}\n\n📌 Media {idx}/{media_count}" if idx == 1 else f"Media {idx}/{media_count}"
                    upload_tasks.append(self.services.file_service.upload_file(
                        file,
                        method=uploader,
                        caption=file_caption
                    ))
                
                results = await asyncio.gather(*upload_tasks, return_exceptions=True)
                
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
                f"📥 Downloaded: {len(downloaded_files)} files\n"
                f"📤 Uploaded: {successful}/{len(downloaded_files)} files"
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Error processing download", url=url, error=error_msg)
            if status_message:
                await status_message.edit_text(f"❌ Error: {error_msg}")
            await self.services.database_service.log_file_operation(
                url, 0, 'download', False, error_msg
            )

    async def handle_download_instagram(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Process Instagram URLs and download media."""
        if not context.args:
            await update.message.reply_text(
                "Please provide an Instagram URL.\n"
                "Usage: /instagram <url>\n\n"
                "Supports:\n"
                "• Posts\n"
                "• Carousels\n"
                "• Reels\n"
                "• Stories\n"
                "• Highlights"
            )
            return

        url = context.args[0]
        await self._process_download(update, url)



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
        
        # Schedule cleanup after bot is fully initialized
        bot._schedule_cleanup()
        
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
