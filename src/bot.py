#!/usr/bin/env python3
"""
Enhanced Telegram Bot with service-based architecture and optimized performance.
"""
import asyncio
import logging
import structlog
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from functools import lru_cache
from rich.console import Console
import re

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

class ContentDetector:
    """Enhanced content detection for Instagram URLs"""
    
    # Comprehensive URL patterns for different Instagram content types
    PATTERNS = {
        'post': [
            r'https?://(?:www\.)?instagram\.com/p/([A-Za-z0-9_-]+)(?:/.*)?$',
            r'https?://(?:www\.)?instagr\.am/p/([A-Za-z0-9_-]+)(?:/.*)?$'
        ],
        'reel': [
            r'https?://(?:www\.)?instagram\.com/reel/([A-Za-z0-9_-]+)(?:/.*)?$',
            r'https?://(?:www\.)?instagram\.com/reels/([A-Za-z0-9_-]+)(?:/.*)?$',
            r'https?://(?:www\.)?instagr\.am/reel/([A-Za-z0-9_-]+)(?:/.*)?$'
        ],
        'story': [
            r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9_.]+)/(\d+)(?:/.*)?$',
            r'https?://(?:www\.)?instagram\.com/stories/([a-zA-Z0-9_.]+)/?$'
        ],
        'highlight': [
            r'https?://(?:www\.)?instagram\.com/stories/highlights/(\d+)(?:/.*)?$',
            r'https?://(?:www\.)?instagram\.com/s/([A-Za-z0-9_-]+)(?:/.*)?$'
        ],
        'profile': [
            r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?$',
            r'https?://(?:www\.)?instagr\.am/([a-zA-Z0-9_.]+)/?$'
        ],
        'tv': [
            r'https?://(?:www\.)?instagram\.com/tv/([A-Za-z0-9_-]+)(?:/.*)?$'
        ]
    }
    
    @classmethod
    def detect_content_type(cls, url: str) -> Tuple[str, str, Optional[str]]:
        """
        Detect Instagram content type from URL.
        
        Returns:
            Tuple of (content_type, identifier, secondary_identifier)
        """
        # Clean the URL
        url = url.strip()
        
        # Check each content type pattern
        for content_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                match = re.match(pattern, url, re.IGNORECASE)
                if match:
                    groups = match.groups()
                    identifier = groups[0] if groups else ""
                    secondary = groups[1] if len(groups) > 1 else None
                    
                    logger.info(f"Detected {content_type}", 
                              url=url, 
                              identifier=identifier, 
                              secondary=secondary)
                    return content_type, identifier, secondary
        
        return 'unknown', url, None
    
    @classmethod
    def is_instagram_url(cls, url: str) -> bool:
        """Check if URL is a valid Instagram URL"""
        instagram_domains = [
            r'https?://(?:www\.)?instagram\.com/',
            r'https?://(?:www\.)?instagr\.am/'
        ]
        
        return any(re.match(domain, url, re.IGNORECASE) for domain in instagram_domains)
    
    @classmethod
    def normalize_url(cls, url: str) -> str:
        """Normalize Instagram URL by removing unnecessary parameters"""
        # Remove query parameters except essential ones for stories
        if '/stories/' in url:
            return url.split('?')[0]  # Keep stories URLs clean
        
        # For other content, remove query params and trailing slash
        url = url.split('?')[0].rstrip('/')
        
        # Normalize domain
        url = url.replace('instagr.am', 'instagram.com')
        url = url.replace('http://', 'https://')
        
        return url

class EnhancedTelegramBot:
    """Enhanced Telegram bot with optimized service architecture."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.services = BotServices.create(config)
        self.detector = ContentDetector()
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
        from src.services.cleanup import CleanupService
        self.cleanup_service = CleanupService(downloads_path)
        
    def _extract_urls_from_text(self, text: str) -> list:
        """Extract URLs from text message."""
        url_pattern = r'https?://[^\s]+'
        return re.findall(url_pattern, text)
        
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
        """Handle messages containing Instagram URLs with enhanced detection."""
        # Get text from either message or caption
        message = update.message or update.channel_post
        if not message:
            return
            
        text = message.text or message.caption
        if not text:
            return
            
        text = text.strip()
        logger.info("Received message", text=text, chat_id=message.chat_id, chat_type=message.chat.type)
        
        # Extract all potential URLs from the message
        urls = self._extract_urls_from_text(text)
        
        # Process each Instagram URL found
        for url in urls:
            if self.detector.is_instagram_url(url):
                # Normalize the URL
                normalized_url = self.detector.normalize_url(url)
                
                # Detect content type
                content_type, identifier, secondary = self.detector.detect_content_type(normalized_url)
                
                logger.info(f"Processing Instagram {content_type}", 
                          url=normalized_url, 
                          identifier=identifier,
                          chat_id=message.chat_id,
                          chat_type=message.chat.type)
                
                await self._process_download(update, normalized_url, content_type, identifier, secondary)
                break  # Process only the first Instagram URL to avoid spam

    def _setup_handlers(self) -> None:
        """Set up command handlers and message handlers."""
        from telegram.ext import MessageHandler, filters
        
        # Add message handler for Instagram URLs with enhanced pattern matching first
        # This ensures URL processing takes precedence over other handlers
        self.bot_app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.CAPTION) &  # Handle both text messages and captions
                ~filters.COMMAND &
                filters.Regex(
                    r'https?://(?:www\.)?(?:instagram\.com|instagr\.am)/[a-zA-Z0-9_/.-]+'
                ),
                self.handle_message,
                block=False  # Non-blocking to handle multiple URLs
            ),
            group=-1  # Highest priority group
        )
        
        # Register command handlers after URL handler
        handlers = [
            ("start", self.handle_start),
            ("stats", self.handle_stats),
            ("instagram", self.handle_download_instagram),
            ("detect", self.handle_detect_url)
        ]
        
        # Add command handlers with group support
        for command, handler in handlers:
            self.bot_app.add_handler(
                CommandHandler(
                    command,
                    handler,
                    filters=filters.ChatType.GROUPS | filters.ChatType.PRIVATE
                )
            )

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command with enhanced content type information."""
        await update.message.reply_text(
            f"👋 Welcome to Instagram Downloader Bot v{BOT_VERSION}\n\n"
            "🚀 **Auto-Detection Features:**\n"
            "• 📷 Posts & Carousels\n"
            "• 🎬 Reels & IGTV\n"
            "• 📱 Stories (requires login)\n"
            "• ⭐ Highlights (requires login)\n"
            "• 👤 Profile detection\n\n"
            "💡 **How to use:**\n"
            "Simply paste any Instagram URL and I'll automatically detect and download the content!\n\n"
            "📋 **Available commands:**\n"
            "/instagram <url> - Download specific content\n"
            "/detect <url> - Test URL detection\n"
            "/stats - Show bot statistics\n\n"
            "⚡ **Supported URL formats:**\n"
            "• instagram.com/p/... (posts)\n"
            "• instagram.com/reel/... (reels)\n"
            "• instagram.com/stories/... (stories)\n"
            "• instagram.com/stories/highlights/... (highlights)\n"
            "• instagram.com/username (profiles)\n"
            "• instagram.com/tv/... (IGTV)\n\n"
            "📝 **Note:** Story and highlight downloads require you to be logged into Instagram."
        )

    async def handle_detect_url(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /detect command to test URL detection."""
        if not context.args:
            await update.message.reply_text(
                "Please provide an Instagram URL to test detection.\n"
                "Usage: /detect <url>"
            )
            return

        url = context.args[0]
        
        if not self.detector.is_instagram_url(url):
            await update.message.reply_text("❌ Not a valid Instagram URL")
            return
        
        normalized_url = self.detector.normalize_url(url)
        content_type, identifier, secondary = self.detector.detect_content_type(normalized_url)
        
        detection_icons = {
            'post': '📷',
            'reel': '🎬',
            'story': '📱',
            'highlight': '⭐',
            'profile': '👤',
            'tv': '📺',
            'unknown': '❓'
        }
        
        icon = detection_icons.get(content_type, '❓')
        
        response = f"🔍 **URL Detection Results:**\n\n"
        response += f"{icon} **Type:** {content_type.title()}\n"
        response += f"🔗 **Original URL:** {url}\n"
        response += f"✨ **Normalized:** {normalized_url}\n"
        response += f"🎯 **Identifier:** {identifier}\n"
        
        if secondary:
            response += f"📝 **Secondary ID:** {secondary}\n"
        
        response += f"\n✅ Ready for download!"
        
        await update.message.reply_text(response, parse_mode='Markdown')
        
    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command with enhanced statistics including content type breakdown."""
        stats = await self.services.database_service.get_statistics()
        
        # Get storage stats
        storage_stats = self.cleanup_service.get_storage_stats()
        
        # Get content type breakdown if available
        content_stats = await self.services.database_service.get_content_type_stats()
        
        response = "📊 **Bot Statistics:**\n\n"
        response += f"📥 **Downloads:**\n"
        response += f"• Total Attempts: {stats.get('total_downloads', 0):,}\n"
        response += f"• Successful: {stats.get('successful_downloads', 0):,}\n"
        response += f"• Failed: {stats.get('failed_downloads', 0):,}\n\n"
        
        response += f"📁 **Files:**\n"
        response += f"• Total Downloaded: {stats.get('total_files_downloaded', 0):,}\n"
        response += f"• Successfully Uploaded: {stats.get('successful_file_uploads', 0):,}\n"
        response += f"• Total Data: {stats.get('total_bytes_downloaded', 0)/1024/1024:.1f} MB\n\n"
        
        if content_stats:
            response += f"📋 **Content Types:**\n"
            for content_type, count in content_stats.items():
                icon = {'post': '📷', 'reel': '🎬', 'story': '📱', 'highlight': '⭐', 'profile': '👤', 'tv': '📺'}.get(content_type, '📄')
                response += f"• {icon} {content_type.title()}: {count:,}\n"
            response += "\n"
        
        response += f"💾 **Storage:**\n"
        response += f"• Current Size: {storage_stats.get('total_size_mb', 0):.1f} MB\n"
        response += f"• Total Directories: {storage_stats.get('total_directories', 0):,}\n"
        response += f"• Old Directories: {storage_stats.get('old_directories', 0):,}"
        
        await update.message.reply_text(response, parse_mode='Markdown')

    async def _process_download(self, update: Update, url: str, content_type: str = None, 
                              identifier: str = None, secondary: str = None) -> None:
        """Enhanced download processing with content type awareness."""
        status_message = None
        try:
            # Auto-detect if not provided
            if not content_type:
                content_type, identifier, secondary = self.detector.detect_content_type(url)
            
            # Create appropriate status message based on content type
            content_icons = {
                'post': '📷',
                'reel': '🎬', 
                'story': '📱',
                'highlight': '⭐',
                'profile': '👤',
                'tv': '📺',
                'unknown': '📄'
            }
            
            icon = content_icons.get(content_type, '📄')
            content_name = content_type.replace('_', ' ').title()
            
            status_message = await update.message.reply_text(
                f"{icon} Detected: {content_name}\n⏬ Starting download..."
            )
            
            # Special handling for different content types
            if content_type == 'profile':
                await status_message.edit_text(
                    f"👤 Profile detected: @{identifier}\n"
                    "Note: Profile downloads will get recent posts. Use specific post URLs for individual content."
                )
            elif content_type in ['story', 'highlight']:
                await status_message.edit_text(
                    f"{icon} Downloading {content_name}...\n"
                    "📝 Note: Stories/Highlights require Instagram login"
                )
            elif content_type == 'unknown':
                await status_message.edit_text(
                    "❓ Unknown content type detected\n⏬ Attempting download..."
                )
            else:
                await status_message.edit_text(
                    f"{icon} Downloading {content_name}..."
                )
            
            # Download content using unified method
            downloaded_files = await self.instagram_downloader.download_content(url)
            if not downloaded_files:
                error_msg = f"❌ Failed to download {content_name.lower()}"
                if content_type in ['story', 'highlight']:
                    error_msg += "\n💡 Tip: Make sure you're logged into Instagram for stories/highlights"
                await status_message.edit_text(error_msg)
                return
                
            await status_message.edit_text(
                f"✅ Downloaded {len(downloaded_files)} files\n"
                f"📤 Starting upload..."
            )
            
            # Extract metadata for the first file
            metadata = await self.instagram_downloader._extract_metadata(downloaded_files[0])
            
            # Build enhanced caption based on content type
            caption = self._build_caption(content_type, metadata, len(downloaded_files), url)
            
            # Process files with progress updates
            successful = await self._upload_files_with_progress(
                downloaded_files, caption, status_message, content_type
            )
                        
            # Update final status with content type info
            final_message = f"{icon} {content_name} processed!\n"
            final_message += f"📥 Downloaded: {len(downloaded_files)} files\n"
            final_message += f"📤 Uploaded: {successful}/{len(downloaded_files)} files"
            
            if successful == len(downloaded_files):
                final_message += "\n🎉 All files uploaded successfully!"
            elif successful > 0:
                final_message += f"\n⚠️ {len(downloaded_files) - successful} files failed to upload"
            else:
                final_message += "\n❌ Upload failed"
                
            await status_message.edit_text(final_message)
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Error processing download", url=url, content_type=content_type, error=error_msg)
            
            if status_message:
                content_name = content_type.replace('_', ' ').title() if content_type else 'content'
                await status_message.edit_text(f"❌ Error downloading {content_name}: {error_msg}")
            
            await self.services.database_service.log_file_operation(
                url, 0, 'download', False, error_msg
            )

    def _build_caption(self, content_type: str, metadata: dict, file_count: int, url: str) -> str:
        """Build enhanced caption based on content type and metadata."""
        caption = ""
        
        # Add content type header
        type_headers = {
            'post': '📷 Instagram Post',
            'reel': '🎬 Instagram Reel', 
            'story': '📱 Instagram Story',
            'highlight': '⭐ Instagram Highlight',
            'profile': '👤 Instagram Profile',
            'tv': '📺 Instagram TV'
        }
        
        if content_type in type_headers:
            caption += f"{type_headers[content_type]}\n"
        
        # Add user info
        if metadata.get('username'):
            caption += f"👤 @{metadata['username']}\n"
        
        # Add content description
        if metadata.get('caption'):
            # Truncate very long captions
            content_caption = metadata['caption']
            if len(content_caption) > 300:
                content_caption = content_caption[:297] + "..."
            caption += f"\n{content_caption}\n"
        
        # Add statistics
        caption += f"\n📱 Total media: {file_count}\n"
        
        if metadata.get('likes'):
            caption += f"❤️ {metadata['likes']:,} likes\n"
        if metadata.get('comments'):
            caption += f"💬 {metadata['comments']:,} comments\n"
        if metadata.get('views'):
            caption += f"👀 {metadata['views']:,} views\n"
        
        # Add source URL
        caption += f"\n🔗 {url}"
        
        return caption

    async def _upload_files_with_progress(self, files: list, caption: str, 
                                        status_message, content_type: str) -> int:
        """Upload files with progress tracking and content type awareness."""
        successful = 0
        batch_size = self.config.upload.batch_size
        total_files = len(files)
        
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            upload_tasks = []
            
            # Update progress
            batch_start = i + 1
            batch_end = min(i + batch_size, total_files)
            await status_message.edit_text(
                f"📤 Uploading files {batch_start}-{batch_end}/{total_files}..."
            )
            
            for idx, file in enumerate(batch, start=i+1):
                file_size = file.stat().st_size
                uploader = self._get_uploader(file_size)
                
                # Create file-specific caption
                if idx == 1:
                    file_caption = f"{caption}\n\n📌 Media {idx}/{total_files}"
                else:
                    file_caption = f"Media {idx}/{total_files}"
                    if content_type in ['post', 'reel'] and total_files > 1:
                        file_caption += f" - Part of {content_type}"
                
                upload_tasks.append(self.services.file_service.upload_file(
                    file,
                    method=uploader,
                    caption=file_caption
                ))
            
            # Execute batch upload
            results = await asyncio.gather(*upload_tasks, return_exceptions=True)
            
            # Process results
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
                    
        return successful

    async def handle_download_instagram(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Process Instagram URLs with enhanced detection and feedback."""
        if not context.args:
            await update.message.reply_text(
                "🔗 Please provide an Instagram URL.\n"
                "Usage: /instagram <url>\n\n"
                "🎯 **Supported content:**\n"
                "• 📷 Posts & Carousels\n"
                "• 🎬 Reels & IGTV\n"
                "• 📱 Stories (login required)\n"
                "• ⭐ Highlights (login required)\n"
                "• 👤 Profiles\n\n"
                "💡 **Tip:** You can also just paste URLs directly!"
            )
            return

        url = context.args[0]
        
        # Validate Instagram URL
        if not self.detector.is_instagram_url(url):
            await update.message.reply_text(
                "❌ Invalid Instagram URL\n\n"
                "Please provide a valid Instagram URL like:\n"
                "• instagram.com/p/...\n"
                "• instagram.com/reel/...\n"
                "• instagram.com/stories/..."
            )
            return
        
        # Normalize and detect
        normalized_url = self.detector.normalize_url(url)
        content_type, identifier, secondary = self.detector.detect_content_type(normalized_url)
        
        await self._process_download(update, normalized_url, content_type, identifier, secondary)



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
