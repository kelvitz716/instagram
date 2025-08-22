#!/usr/bin/env python3
"""
Enhanced Telegram Bot with service-based architecture for better maintainability.
"""
import asyncio
import logging
import structlog
from pathlib import Path
from typing import Optional
from rich.console import Console

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient

from src.core.config import BotConfig, TelegramConfig, UploadConfig, InstagramConfig, DatabaseConfig
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.progress import ProgressTracker

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
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
    """Enhanced Telegram bot with service-based architecture."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.downloads_path = config.downloads_path
        self.downloads_path.mkdir(parents=True, exist_ok=True)

        # Initialize services
        self.db = DatabaseService(config.database)
        self.progress_tracker = ProgressTracker()
        self.instagram_downloader = InstagramDownloader(
            config.instagram,
            self.downloads_path
        )
        
        # Initialize upload service and register uploaders
        self.upload_service = FileUploadService(config.upload)
        
        # Telegram clients (initialized in initialize())
        self.bot_app: Optional[Application] = None
        self.telethon_client: Optional[TelegramClient] = None

    async def initialize(self):
        """Initialize the bot and all its services."""
        try:
            # Initialize database
            await self.db.initialize()
            
            # Initialize Telegram bot
            self.bot_app = Application.builder().token(self.config.telegram.bot_token).build()
            self._setup_handlers()
            
            # Initialize Telethon client
            self.telethon_client = TelegramClient(
                self.config.telegram.session_name,
                self.config.telegram.api_id,
                self.config.telegram.api_hash
            )
            await self.telethon_client.start()
            
            # Initialize uploaders
            bot_api_uploader = BotAPIUploader(
                self.config.telegram.bot_token,
                self.config.telegram.target_chat_id
            )
            telethon_uploader = TelethonUploader(
                self.telethon_client,
                self.config.telegram.target_chat_id,
                self.config.telegram.api_id,
                self.config.telegram.api_hash
            )
            
            # Register uploaders with upload service
            self.upload_service.register_uploader('bot_api', bot_api_uploader)
            self.upload_service.register_uploader('telethon', telethon_uploader)
            
            logger.info("Bot initialized successfully", version=BOT_VERSION)
            
        except Exception as e:
            logger.error("Failed to initialize bot", error=str(e), exc_info=True)
            raise

    def _setup_handlers(self):
        """Set up command handlers."""
        self.bot_app.add_handler(CommandHandler("start", self.handle_start))
        self.bot_app.add_handler(CommandHandler("stats", self.handle_stats))
        self.bot_app.add_handler(CommandHandler("instagram", self.handle_download_instagram))

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            f"👋 Welcome to Instagram Downloader Bot v{BOT_VERSION}\n\n"
            "Available commands:\n"
            "/instagram <url> - Download Instagram post, carousel, or reel\n"
            "/stats - Show bot statistics\n\n"
            "Simply paste the URL of any Instagram post, carousel, or reel to download it.\n"
            "Note: Stories and highlights are not supported as they require special access."
        )

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        stats = await self.db.get_statistics()
        await update.message.reply_text(
            "📊 Bot Statistics:\n\n"
            f"Total Downloads: {stats.get('total_downloads', 0)}\n"
            f"Successful: {stats.get('successful_downloads', 0)}\n"
            f"Failed: {stats.get('failed_downloads', 0)}\n"
            f"Total Uploads: {stats.get('total_uploads', 0)}\n"
            f"Successful: {stats.get('successful_uploads', 0)}\n"
            f"Failed: {stats.get('failed_uploads', 0)}"
        )

    async def handle_download_instagram(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /instagram command."""
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
            # Download files
            files = await self.instagram_downloader.download_post(url)
            if not files:
                await status_message.edit_text("❌ Failed to download content")
                return

            await status_message.edit_text(
                f"✅ Downloaded {len(files)} files\n"
                "📤 Starting upload..."
            )

            # Upload files
            successful = 0
            for file in files:
                if await self.upload_service.upload_file(file):
                    successful += 1
                    await self.db.log_file_operation(
                        str(file),
                        file.stat().st_size,
                        'upload',
                        True
                    )
                else:
                    await self.db.log_file_operation(
                        str(file),
                        file.stat().st_size,
                        'upload',
                        False,
                        "Upload failed"
                    )

            # Update final status
            await status_message.edit_text(
                f"✅ Process complete!\n"
                f"📥 Downloaded: {len(files)} files\n"
                f"📤 Uploaded: {successful}/{len(files)} files"
            )

        except Exception as e:
            logger.error("Error processing Instagram URL", url=url, error=str(e))
            await status_message.edit_text(f"❌ Error: {str(e)}")
            await self.db.log_file_operation(
                url,
                0,
                'download',
                False,
                str(e)
            )



    async def shutdown(self):
        """Shutdown the bot and cleanup resources."""
        try:
            # First stop polling
            if self.bot_app and self.bot_app.updater:
                await self.bot_app.updater.stop()
            
            # Shutdown the bot application
            if self.bot_app:
                await self.bot_app.stop()
                await self.bot_app.shutdown()
            
            # Disconnect Telethon client
            if self.telethon_client:
                await self.telethon_client.disconnect()
            
            # Close database connection
            await self.db.close()
            
            logger.info("Bot shutdown complete")
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))

async def main():
    """Initialize and run the bot."""
    from src.core.load_config import load_configuration
    
    # Load configuration from environment
    config = load_configuration()
    
    # Create and initialize bot
    bot = EnhancedTelegramBot(config)
    await bot.initialize()
    
    try:
        # Start polling in the background
        await bot.bot_app.initialize()
        await bot.bot_app.start()
        await bot.bot_app.updater.start_polling()
        
        # Keep the bot running until interrupted
        try:
            await asyncio.Event().wait()  # Run forever
        except asyncio.CancelledError:
            pass
    finally:
        # Ensure proper cleanup
        await bot.shutdown()

def run_bot():
    """Run the bot with proper event loop handling"""
    try:
        # Configure logging first
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Run the bot
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    run_bot()
