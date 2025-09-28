#!/usr/bin/env python3
"""
Instagram Content Downloader Bot

A Telegram bot that automatically detects and downloads content from Instagram URLs.
Supports posts, reels, stories, highlights, and profiles with optimized performance
and service-based architecture.

Features:
- Automatic URL detection and content type identification
- Support for multiple Instagram content types
- Optimized download and upload handling
- Progress tracking and status updates
- Database logging and statistics
- Periodic cleanup of downloaded files

Author: @kelvitz716
Version: 2.0.0
"""

# Standard library imports
import asyncio
import json
import logging
import pathlib
import re
import time
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Third-party imports
import structlog
from rich.console import Console
from telegram import Message, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, 
    filters, ContextTypes
)
from telegram import error as telegram_error
from telethon import TelegramClient

# Core imports
from src.core.config import BotConfig
from src.core.services import BotServices
from src.core.resilience.retry import with_retry
from src.core.resilience.circuit_breaker import with_circuit_breaker, ServiceUnavailableError
from src.core.resilience.recovery import SessionRecovery, StateRecovery
from src.core.help_command import HelpCommandMixin
from src.core.session_commands import SessionCommands
from src.core.session_manager import InstagramSessionManager

# Local imports
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.progress import ProgressTracker
from src.services.session_storage import SessionStorageService, SessionStorageError
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.progress import ProgressTracker
from src.services.session_storage import SessionStorageService, SessionStorageError
from src.services.telegram_session_storage import TelegramSessionStorage, TelegramSessionStorageError

# Global constants for optimization
CONTENT_ICONS = {
    'post': '📷',
    'reel': '🎬', 
    'story': '📱',
    'highlight': '⭐',
    'profile': '👤',
    'tv': '📺',
    'unknown': '📄'
}

# Base URL pattern components for optimization
BASE_INSTAGRAM = r'https?://(?:www\.)?'
INSTAGRAM_DOMAINS = ['instagram.com', 'instagr.am']
PATH_END = r'(?:/.*)?$'

# Regular expressions pre-compiled for performance
URL_PATTERN = re.compile(r'https?://[^\s]+', re.I)
INSTAGRAM_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:instagram\.com|instagr\.am)/[a-zA-Z0-9_/.-]+',
    re.I
)

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
    """Enhanced content detection for Instagram URLs with pattern matching."""
    
    # Pre-compile patterns for better performance
    PATTERNS = {
        'post': [
            re.compile(f"{BASE_INSTAGRAM}{domain}/p/([A-Za-z0-9_-]+){PATH_END}", re.I)
            for domain in INSTAGRAM_DOMAINS
        ],
        'reel': [
            *[re.compile(f"{BASE_INSTAGRAM}instagram.com/reel(?:s)?/([A-Za-z0-9_-]+){PATH_END}", re.I)],
            *[re.compile(f"{BASE_INSTAGRAM}instagr.am/reel/([A-Za-z0-9_-]+){PATH_END}", re.I)]
        ],
        'story': [
            re.compile(f"{BASE_INSTAGRAM}instagram.com/stories/([a-zA-Z0-9_.]+)(?:/([0-9]+))?{PATH_END}", re.I)
        ],
        'highlight': [
            re.compile(f"{BASE_INSTAGRAM}instagram.com/stories/highlights/([0-9]+){PATH_END}", re.I),
            re.compile(f"{BASE_INSTAGRAM}instagram.com/s/([A-Za-z0-9_-]+){PATH_END}", re.I)
        ],
        'profile': [
            re.compile(f"{BASE_INSTAGRAM}{domain}/([a-zA-Z0-9_.]+)/?$", re.I)
            for domain in INSTAGRAM_DOMAINS
        ],
        'tv': [
            re.compile(f"{BASE_INSTAGRAM}instagram.com/tv/([A-Za-z0-9_-]+){PATH_END}", re.I)
        ]
    }
    
    @classmethod
    def detect_content_type(cls, url: str) -> Tuple[str, str, Optional[str]]:
        """
        Detect Instagram content type from URL.
        
        Args:
            url (str): Instagram URL to analyze
            
        Returns:
            Tuple[str, str, Optional[str]]: (content_type, identifier, secondary_identifier)
            
        Note:
            Uses pre-compiled regex patterns for better performance
        """
        # Clean the URL
        url = url.strip()
        
        # Check each content type pattern
        for content_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                # Patterns are pre-compiled, no need to pass flags
                match = pattern.match(url)
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
        """
        Check if URL is a valid Instagram URL
        
        Args:
            url (str): URL to validate
            
        Returns:
            bool: True if URL is a valid Instagram URL
        """
        # Use pre-compiled pattern for validation
        return bool(INSTAGRAM_URL_PATTERN.match(url))
    
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

class EnhancedTelegramBot(SessionCommands, HelpCommandMixin):
    """
    Enhanced Telegram bot with optimized service architecture for Instagram content.
    
    This class manages the main bot functionality including:
    - Service initialization and management
    - Message handling and content detection
    - File download and upload operations
    - Database logging and cleanup
    - Session management with cookie file support
    - Session management with cookies.txt support
    
    Attributes:
        config (BotConfig): Bot configuration including API keys and settings
        services (BotServices): Service container for all bot services
        session_storage (SessionStorageService): Manages Instagram session storage
        detector (ContentDetector): Instagram URL detection and parsing
        _cache (Dict[str, Any]): Internal cache for optimization
    """

    def __init__(self, config: BotConfig) -> None:
        """
        Initialize the bot with configuration and services.
        
        Args:
            config (BotConfig): Bot configuration instance containing all settings
        """
        super().__init__()
        self.config = config
        self.services = BotServices.create(config)
        self.detector = ContentDetector()
        self._setup_directories()
        self._cache: Dict[str, Any] = {}
        self._user_states: Dict[int, Dict[str, Any]] = {}
        
        # Initialize recovery services
        self.session_recovery = SessionRecovery(self.services)
        self.state_recovery = StateRecovery(self.services)
        
    def _setup_directories(self) -> None:
        """
        Setup required directories for bot operation with error handling.
        
        Creates directories for:
        - Downloads: Temporary storage for downloaded content
        - Uploads: Staging area for content to be uploaded
        - Temp: General temporary file storage
        
        Raises:
            Exception: If directory creation fails
        """
        try:
            for path in [self.config.downloads_path, self.config.uploads_path, self.config.temp_path]:
                path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create directories", error=str(e))
            raise
            
    @lru_cache(maxsize=1)
    def _get_uploader(self, file_size: int) -> str:
        """
        Get the appropriate uploader based on file size with caching.
        
        Args:
            file_size (int): Size of the file in bytes
            
        Returns:
            str: 'telethon' for large files, 'bot_api' for smaller files
        """
        return 'telethon' if file_size > self.config.upload.large_file_threshold else 'bot_api'

    async def initialize(self) -> None:
        """
        Initialize bot services in a specific sequence with resilience features.
        
        Sequence:
        1. Database initialization
        2. Telegram client setup
        3. Upload services configuration
        4. Instagram service setup
        5. Resume any pending downloads
        
        Raises:
            Exception: If any initialization step fails
        """
        try:
            # Initialize components sequentially
            await self._initialize_database()

            # Add Telegram session table to database
            await self._create_telegram_session_table()

            # Initialize Telegram with persistent sessions
            await self._initialize_telegram()

            # Initialize other services
            self._initialize_instagram()
            self.services.instagram_service = self.instagram_downloader
            self.services.session_storage = self.session_storage

            await self._initialize_uploaders()

            # Schedule maintenance tasks
            await self._schedule_session_maintenance()

            # Resume any interrupted downloads
            try:
                pending_downloads = await self.state_recovery.get_pending_downloads()
                if pending_downloads:
                    logger.info(f"Found {len(pending_downloads)} interrupted downloads  to resume")
                    for state in pending_downloads:
                        await self.state_recovery.resume_download(state)
            except Exception as e:
                logger.error("Failed to resume downloads", error=str(e))

            logger.info("Bot initialized successfully with persistent sessions",    version=BOT_VERSION)

        except Exception as e:
            logger.error("Failed to initialize bot", error=str(e))
            raise

    async def _create_telegram_session_table(self):
        """Ensure the telegram_sessions table exists."""
        try:
            conn = self.services.database_service._pool.acquire()
            try:
                await self.services.database_service._create_telegram_sessions_table    (conn)
            finally:
                self.services.database_service._pool.release(conn)
        except Exception as e:
            logger.error(f"Failed to create telegram_sessions table: {e}")
            raise

    async def _schedule_session_maintenance(self) -> None:
        """Schedule periodic maintenance of stored sessions."""
        async def session_cleanup():
            try:
                # Clean up expired Telegram sessions
                deleted_count = await self.telegram_session_storage.    cleanup_old_sessions()
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} expired Telegram   sessions")

                # Clean up expired Instagram sessions
                if hasattr(self, 'session_storage'):
                    instagram_deleted = await self.session_storage. cleanup_expired_sessions()
                    if instagram_deleted > 0:
                        logger.info(f"Cleaned up {instagram_deleted} expired Instagram  sessions")

            except Exception as e:
                logger.error(f"Session maintenance failed: {e}")

        # Run session cleanup daily
        self.bot_app.job_queue.run_repeating(session_cleanup, interval=24*60*60)
            
    def _initialize_instagram(self) -> None:
        """Initialize Instagram downloader and cleanup service."""
        downloads_path = self.config.downloads_path
        
        # Initialize session storage service first
        self.session_storage = SessionStorageService(
            self.services.database_service,
            downloads_path
        )

        # Create session manager instance
        self.session_manager = InstagramSessionManager(
            downloads_path=downloads_path,
            cookies_file=None  # Start without cookies, they'll be loaded per user
        )

        # Initialize Instagram downloader without cookies
        self.instagram_downloader = InstagramDownloader(
            self.config.instagram,
            downloads_path=downloads_path
        )
        
        # Initialize cleanup service with 2-day retention
        from src.services.cleanup import CleanupService
        self.cleanup_service = CleanupService(downloads_path, max_age_days=2)
        
    async def handle_cleanup(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /cleanup command for manual media cleanup."""
        # Send initial status
        status_message = await update.message.reply_text(
            "🧹 Starting cleanup of all media files..."
        )
        
        try:
            # Clean up all media files
            dirs_removed, bytes_freed = await self.cleanup_service.cleanup_all_media()
            
            if dirs_removed > 0:
                await self._safe_edit_message(
                    status_message,
                    f"✅ Cleanup complete!\n\n"
                    f"• Removed {dirs_removed:,} directories\n"
                    f"• Freed {bytes_freed/1024/1024:.1f} MB of space"
                )
            else:
                await self._safe_edit_message(
                    status_message,
                    "✨ No media files to clean up!"
                )
                
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
            await self._safe_edit_message(
                status_message,
                f"❌ Error during cleanup: {str(e)}"
            )
        
    def _extract_urls_from_text(self, text: str) -> List[str]:
        """Extract URLs from text message using pre-compiled pattern."""
        return URL_PATTERN.findall(text)
        
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
        """Initialize Telegram clients with persistent session management."""
        # Initialize session storage
        self.telegram_session_storage = TelegramSessionStorage(
            self.services.database_service,
            self.config.downloads_path / "sessions"
        )

        # Try to get existing session first
        stored_session = await self.telegram_session_storage.get_active_session()

        if stored_session and await self._validate_existing_session(stored_session):
            logger.info("Using existing Telegram session")
            session_file_path = Path(stored_session['session_file_path'])
        else:
            logger.info("No valid existing session, creating new one")
            session_file_path = await self._create_new_telegram_session()

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

        # Register command handlers
        self.bot_app.add_handler(CommandHandler("start", self.handle_start))
        self.bot_app.add_handler(CommandHandler("help", self.handle_help))
        self.bot_app.add_handler(CommandHandler("stats", self.handle_stats))
        self.bot_app.add_handler(CommandHandler("cleanup", self.handle_cleanup))
        self.bot_app.add_handler(CommandHandler("telegram_status", self.    handle_telegram_session_status))

        # Session management handlers for Instagram
        self.bot_app.add_handler(CommandHandler("session_upload", self. handle_session_upload_start))
        self.bot_app.add_handler(MessageHandler(
            filters.Document.ALL & ~filters.COMMAND,
            self.handle_session_file_upload,
            block=False
        ))
        self.bot_app.add_handler(CommandHandler("session_list", self.   handle_session_list))
        self.bot_app.add_handler(CallbackQueryHandler(
            self.handle_session_button, 
            pattern=r'^(activate|delete)_session_\d+$'
        ))

        # URL handling
        self.bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.  handle_message))

        # Initialize Telethon with the persistent session
        session_name = str(session_file_path).replace('.session', '')
        self.telethon_client = TelegramClient(
            session_name,
            self.config.telegram.api_id,
            self.config.telegram.api_hash,
            connection_retries=self.config.telegram.network_retry_attempts,
            retry_delay=self.config.telegram.flood_control_base_delay,
            auto_reconnect=True
        )

        await self.telethon_client.start()

        # Update session usage
        if stored_session:
            await self.telegram_session_storage.update_session_usage(stored_session ['id'])

    async def _validate_existing_session(self, session: Dict[str, Any]) -> bool:
        """Validate that an existing session is still usable."""
        try:
            return await self.telegram_session_storage.validate_stored_session(
                self.config.telegram.api_id,
                self.config.telegram.api_hash
            )
        except Exception as e:
            logger.warning(f"Session validation failed: {e}")
            return False

    async def _create_new_telegram_session(self) -> Path:
        """Create a new Telegram session interactively and store it."""
        import tempfile

        # Create temporary session for initial login
        with tempfile.NamedTemporaryFile(suffix='.session', delete=False) as temp_file:
            temp_session_path = Path(temp_file.name)

        temp_session_name = str(temp_session_path).replace('.session', '')

        try:
            # Create temporary client for authentication
            temp_client = TelegramClient(
                temp_session_name,
                self.config.telegram.api_id,
                self.config.telegram.api_hash
            )

            logger.info("Starting Telegram authentication...")
            await temp_client.start()

            # Get user info
            me = await temp_client.get_me()
            phone_number = me.phone if me.phone else "unknown"

            user_info = {
                "id": me.id,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "username": me.username,
                "phone": phone_number
            }

            logger.info(f"Authenticated as {me.first_name} ({phone_number})")

            # Disconnect temporary client
            await temp_client.disconnect()

            # Store the session permanently
            session_id = await self.telegram_session_storage.store_telegram_session(
                temp_session_path,
                phone_number,
                user_info
            )

            # Get the stored session path
            stored_path = self.telegram_session_storage.get_session_file_path()

            logger.info(f"Telegram session stored successfully with ID {session_id}")
            return stored_path

        except Exception as e:
            logger.error(f"Failed to create Telegram session: {e}")
            raise
        finally:
            # Clean up temporary files
            for temp_path in [temp_session_path, Path(f"{temp_session_name}.session")]:
                if temp_path.exists():
                    try:
                        temp_path.unlink()
                    except Exception:
                        pass

    async def handle_telegram_session_status(self, update: Update, context:     ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /telegram_status command to show Telegram session status."""
        try:
            session = await self.telegram_session_storage.get_active_session()

            if not session:
                await update.message.reply_text(
                    "❌ No active Telegram session found.\n"
                    "This shouldn't happen if the bot is running properly."
                )
                return

            session_data = session.get('session_data', {})
            user_info = session_data.get('user_info', {})

            response = "📱 **Telegram Session Status**\n\n"
            response += f"✅ **Status:** Active\n"
            response += f"📞 **Phone:** {session['phone_number']}\n"
            response += f"👤 **Name:** {user_info.get('first_name', 'Unknown')}"

            if user_info.get('username'):
                response += f" (@{user_info['username']})"

            response += f"\n📅 **Created:** {session['created_at'][:10]}\n"
            response += f"🔄 **Last Used:** {session_data.get('last_used', 'Unknown')   [:19]}\n"

            # Check if session file exists
            session_file = Path(session['session_file_path'])
            if session_file.exists():
                file_size = session_file.stat().st_size
                response += f"📁 **File Size:** {file_size} bytes\n"
            else:
                response += "⚠️ **Warning:** Session file not found on disk\n"

            await update.message.reply_text(response, parse_mode='Markdown')

        except Exception as e:
            logger.error(f"Failed to get session status: {e}")
            await update.message.reply_text(
                "❌ Error retrieving session status. Check logs for details."
            )

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
        # Add message handler for Instagram URLs with enhanced pattern matching first
        # This ensures URL processing takes precedence over other handlers
        self.bot_app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.CAPTION) &  # Handle both text messages and captions
                ~filters.COMMAND &
                filters.Regex(INSTAGRAM_URL_PATTERN.pattern),
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

    async def _safe_edit_message(self, message: Message, text: str, retry_after: Optional[int] = None) -> bool:
        """
        Safely edit a message with rate limit handling.
        
        Args:
            message (Message): Message to edit
            text (str): New message text
            retry_after (Optional[int]): Override for retry delay in seconds
            
        Returns:
            bool: True if edit was successful, False if rate limited
        """
        try:
            await message.edit_text(text)
            return True
            
        except telegram_error.RetryAfter as e:
            retry_after = retry_after or e.retry_after
            logger.warning(f"Rate limited, waiting {retry_after}s", error=str(e))
            await asyncio.sleep(retry_after + 1)  # Add 1s buffer
            
            try:
                await message.edit_text(text)
                return True
            except Exception:
                return False
                
        except Exception as e:
            logger.error("Failed to edit message", error=str(e))
            return False

    @with_circuit_breaker(failure_threshold=5, reset_timeout=300)
    @with_retry(max_retries=3, exceptions=[ConnectionError, TimeoutError])
    async def _process_download(self, update: Update, url: str, content_type: str = None, 
                              identifier: str = None, secondary: str = None) -> None:
        """Enhanced download processing with content type awareness and resilience."""
        if not update.effective_user:
            return
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
            
            # Send initial status with error handling
            try:
                status_message = await update.message.reply_text(
                    f"{icon} Detected: {content_name}\n⏬ Starting download..."
                )
            except telegram_error.RetryAfter as e:
                # If rate limited on first message, wait and try again
                await asyncio.sleep(e.retry_after + 1)
                status_message = await update.message.reply_text(
                    f"{icon} Detected: {content_name}\n⏬ Starting download..."
                )
            
            # Special handling for different content types with rate limit handling
            msg_text = ""
            if content_type == 'profile':
                msg_text = f"👤 Profile detected: @{identifier}\nNote: Profile downloads will get recent posts. Use specific post URLs for individual content."
            elif content_type in ['story', 'highlight']:
                msg_text = f"{icon} Downloading {content_name}...\n📝 Note: Stories/Highlights require Instagram login"
            elif content_type == 'unknown':
                msg_text = "❓ Unknown content type detected\n⏬ Attempting download..."
            else:
                msg_text = f"{icon} Downloading {content_name}..."
                
            await self._safe_edit_message(status_message, msg_text)
            
            # Get active session for the user
            session = await self.session_storage.get_active_session(update.effective_user.id)
            if not session:
                await status_message.edit_text(
                    "❌ No active Instagram session found.\n"
                    "Please use /session_upload to upload a cookies.txt file "
                    "or ensure you're logged into Instagram in Firefox."
                )
                return

            try:
                # Initialize downloader with session
                downloader = InstagramDownloader(
                    self.config.instagram,
                    Path(self.config.downloads_path),
                    cookies_file=Path(session['cookies_file_path']) if session['cookies_file_path'] else None
                )
                
                # Download content
                downloaded_files = await downloader.download_content(url)
                
            except Exception as e:
                # Try session recovery if download fails
                logger.warning("Download failed, attempting session recovery", error=str(e))
                if await self.session_recovery.recover_instagram_session():
                    # Retry download after session recovery
                    downloaded_files = await self.instagram_downloader.download_content(url)
                else:
                    raise
                    
            if not downloaded_files:
                error_msg = f"❌ Failed to download {content_name.lower()}"
                if content_type in ['story', 'highlight']:
                    error_msg += "\n💡 Tip: Make sure you're logged into Instagram for stories/highlights"
                await self._safe_edit_message(status_message, error_msg)
                return
                
            # Save download state for recovery
            await self.state_recovery.save_download_state(url, downloaded_files, status_message)
                
            await self._safe_edit_message(
                status_message,
                f"✅ Downloaded {len(downloaded_files)} files\n📤 Starting upload..."
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
                
            await self._safe_edit_message(status_message, final_message)
            
        except SessionStorageError as se:
            error_msg = str(se)
            logger.error("Session error while downloading", url=url, content_type=content_type, error=error_msg)
            
            if status_message:
                content_name = content_type.replace('_', ' ').title() if content_type else 'content'
                if "Failed to get active session" in error_msg:
                    await self._safe_edit_message(
                        status_message,
                        "❌ No active Instagram session found.\n"
                        "Please upload a valid session using /session_upload command first."
                    )
                else:
                    await self._safe_edit_message(
                        status_message,
                        f"❌ Session error: {error_msg}\n"
                        "Try uploading a new session using /session_upload"
                    )
            
            await self.services.database_service.log_file_operation(
                url, 0, 'download', False, f"Session error: {error_msg}"
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Error processing download", url=url, content_type=content_type, error=error_msg)
            
            if status_message:
                content_name = content_type.replace('_', ' ').title() if content_type else 'content'
                await self._safe_edit_message(status_message, f"❌ Error downloading {content_name}: {error_msg}")
            
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

    @with_circuit_breaker(failure_threshold=5, reset_timeout=300)
    @with_retry(
        max_retries=3,
        exceptions=[ConnectionError, TimeoutError, telegram_error.RetryAfter],
        initial_delay=1.0,
        max_delay=60.0,
        backoff_factor=2.0,
        jitter=True
    )
    async def _upload_files_with_progress(
        self, 
        files: List[Path], 
        caption: str,
        status_message: Message, 
        content_type: str
    ) -> int:
        """
        Upload files with progress tracking, content type awareness, and resilience.
        
        Args:
            files (List[Path]): List of files to upload
            caption (str): Base caption for media files
            status_message (Message): Message to update with progress
            content_type (str): Type of content being uploaded
            
        Returns:
            int: Number of successfully uploaded files
            
        Note:
            Files are uploaded in batches to optimize performance and handle rate limits
            with automatic retries and circuit breaker protection
        """
        successful = 0
        batch_size = self.config.upload.batch_size
        total_files = len(files)
        retry_delay = 1  # Start with 1 second delay between uploads
        
        for i in range(0, len(files), batch_size):
            try:
                batch = files[i:i + batch_size]
                batch_start = i + 1
                batch_end = min(i + batch_size, total_files)
                
                # Update progress with rate limit handling
                await self._safe_edit_message(
                    status_message,
                    f"📤 Uploading files {batch_start}-{batch_end}/{total_files}..."
                )
                
                # Upload files sequentially for better rate limit handling
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
                    
                    # Try to upload with retries
                    max_retries = 3
                    for retry in range(max_retries):
                        try:
                            result = await self.services.file_service.upload_file(
                                file,
                                method=uploader,
                                caption=file_caption
                            )
                            
                            # Process result
                            if result:
                                successful += 1
                                retry_delay = max(1, retry_delay / 2)  # Decrease delay on success
                            else:
                                retry_delay = min(60, retry_delay * 2)  # Double delay on failure
                            
                            # Log operation
                            await self.services.database_service.log_file_operation(
                                str(file),
                                file.stat().st_size,
                                'upload',
                                bool(result),
                                None if result else "Upload failed"
                            )
                            
                            break  # Success, no need to retry
                            
                        except telegram_error.RetryAfter as e:
                            if retry < max_retries - 1:
                                logger.warning(
                                    f"Rate limited on file {idx}, waiting {e.retry_after}s",
                                    retry=retry+1,
                                    file=str(file)
                                )
                                # Update status to inform user
                                await self._safe_edit_message(
                                    status_message,
                                    f"⏳ Rate limited, waiting {e.retry_after}s...\n"
                                    f"📤 Uploading files {batch_start}-{batch_end}/{total_files}"
                                )
                                await asyncio.sleep(e.retry_after + 1)
                                retry_delay = e.retry_after  # Use the server's suggested delay
                                continue
                            else:
                                raise  # Max retries reached
                                
                        except Exception as e:
                            logger.error(
                                f"Upload error on file {idx}",
                                error=str(e),
                                file=str(file)
                            )
                            # Log failed operation
                            await self.services.database_service.log_file_operation(
                                str(file),
                                file.stat().st_size,
                                'upload',
                                False,
                                str(e)
                            )
                            break  # Skip this file
                            
                    # Wait between files to avoid rate limits
                    if idx < batch_end:
                        await asyncio.sleep(retry_delay)
                        
            except telegram_error.RetryAfter as e:
                logger.warning(
                    f"Batch upload rate limited, waiting {e.retry_after}s",
                    batch_start=batch_start,
                    batch_end=batch_end
                )
                await self._safe_edit_message(
                    status_message,
                    f"⏳ Rate limited, waiting {e.retry_after}s before next batch..."
                )
                await asyncio.sleep(e.retry_after + 1)
                retry_delay = e.retry_after
                i -= batch_size  # Retry this batch
                continue
                
            except Exception as e:
                logger.error("Batch upload failed", error=str(e))
                await self._safe_edit_message(
                    status_message,
                    f"⚠️ Error uploading batch {batch_start}-{batch_end}: {str(e)}"
                )
                continue
                
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



    async def handle_session_upload_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Start the session upload process and wait for file."""
        if not update.effective_user:
            return

        if context.user_data.get('waiting_for_cookie_file'):
            # Already waiting for a file
            await update.message.reply_text(
                "⚠️ I'm already waiting for your cookie file.\n"
                "Please upload it or wait for the current session to timeout.",
                parse_mode='Markdown'
            )
            return
            
        # Start waiting for file
        context.user_data['waiting_for_cookie_file'] = True
        context.user_data['cookie_upload_expires'] = time.time() + 30
        
        # Send instructions
        status_message = await update.message.reply_text(
            "📤 **Upload Instagram Cookie File**\n\n"
            "🕒 You have 30 seconds to send your `cookies.txt` file.\n\n"
            "🔍 **Instructions:**\n"
            "1. Use a cookie exporter extension to save Instagram cookies\n"
            "2. Export in Netscape format as 'cookies.txt'\n"
            "3. Upload the file here\n\n"
            "⚠️ File must be in Netscape cookie format and contain Instagram cookies.\n"
            "⏳ Waiting for file...",
            parse_mode='Markdown'
        )
        
        # Store message ID for timeout handling
        context.user_data['status_message_id'] = status_message.message_id
        context.user_data['status_chat_id'] = status_message.chat_id
        
        # Schedule timeout
        async def timeout_handler():
            await asyncio.sleep(30)
            try:
                if context.user_data.get('waiting_for_cookie_file'):
                    context.user_data.pop('waiting_for_cookie_file', None)
                    context.user_data.pop('cookie_upload_expires', None)
                    
                    # Try to edit the original message
                    try:
                        await context.bot.edit_message_text(
                            chat_id=context.user_data['status_chat_id'],
                            message_id=context.user_data['status_message_id'],
                            text="⌛ Session upload timed out.\nUse /session_upload to try again."
                        )
                    except Exception:
                        pass  # Message might have been deleted or edited
            except Exception as e:
                logger.error(f"Error in timeout handler: {e}")
                
        asyncio.create_task(timeout_handler())

    async def handle_session_file_upload(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle cookie file upload after /session_upload command."""
        user = update.effective_user
        
        # Ignore if we're not waiting for a file from this user
        if not context.user_data.get('waiting_for_cookie_file'):
            return
        
        # Check if upload window expired
        if time.time() > context.user_data.get('cookie_upload_expires', 0):
            # Clean up user data
            context.user_data.pop('waiting_for_cookie_file', None)
            context.user_data.pop('cookie_upload_expires', None)
            
            await update.message.reply_text(
                "⌛ Upload window expired. Please use /session_upload to try again."
            )
            return

        # Send initial status
        status_message = await update.message.reply_text(
            "⏳ Downloading and validating cookie file..."
        )

        try:
            # Clear waiting flags after status message to allow edits if needed
            context.user_data.pop('waiting_for_cookie_file', None)
            context.user_data.pop('cookie_upload_expires', None)
            context.user_data.pop('status_message_id', None)
            context.user_data.pop('status_chat_id', None)

            # Download the file
            file = await context.bot.get_file(update.message.document.file_id)
            
            # Create user-specific cookie file paths
            cookies_dir = self.config.downloads_path / 'cookies'
            user_cookie_dir = cookies_dir / str(user.id)
            user_cookie_dir.mkdir(parents=True, exist_ok=True)
            
            # Create temp and final paths
            temp_cookie_file = user_cookie_dir / f"temp_cookies_{int(time.time())}.txt"
            final_cookie_file = user_cookie_dir / "cookies.txt"
            
            await file.download_to_drive(temp_cookie_file)

            try:
                # Create temporary session manager for validation
                temp_session_manager = InstagramSessionManager(
                    downloads_path=self.config.downloads_path,
                    cookies_file=temp_cookie_file
                )

                # Load and validate the cookies
                await self._safe_edit_message(status_message, "🔍 Validating cookies...")
                # Load and validate cookies
                session_cookies = await temp_session_manager.load_cookies_from_file(temp_cookie_file)

                # Try an Instagram API call to verify the session
                is_valid, message = await temp_session_manager._test_session()
                
                if not is_valid:
                    if temp_cookie_file.exists():
                        temp_cookie_file.unlink()
                    await self._safe_edit_message(
                        status_message,
                        f"❌ Invalid cookies: {message}\n\n"
                        "Please ensure you're logged into Instagram and try exporting cookies again."
                    )
                    return
                    
                # Clean up any existing sessions for this user
                await self._safe_edit_message(status_message, "⏳ Managing sessions...")

                # Store the session in the database
                username = session_cookies.get('ds_user_id', 'unknown')  # Get username from cookies
                
                # Move temp cookie file to permanent location
                if final_cookie_file.exists():
                    final_cookie_file.unlink()  # Remove old cookie file if exists
                    logger.info(f"Removed existing cookie file for user {user.id}")
                temp_cookie_file.rename(final_cookie_file)  # Move temp file to permanent location
                logger.info(f"Created new cookie file at {final_cookie_file}")

                # Clean up any leftover temp files
                for temp_file in user_cookie_dir.glob("temp_cookies_*.txt"):
                    if temp_file != final_cookie_file:
                        try:
                            temp_file.unlink()
                            logger.info(f"Cleaned up temporary cookie file: {temp_file}")
                        except Exception as e:
                            logger.warning(f"Failed to clean up temporary file {temp_file}: {e}")
                
                # Create JSON-serializable session data
                session_data = {
                    "status": "valid",
                    "last_checked": datetime.now().isoformat(),
                    "cookie_file": str(final_cookie_file)
                }
                
                session_id = await self.services.session_storage.store_session(
                    user_id=user.id,
                    username=username,
                    session_type='cookie_file',
                    session_data=session_data,
                    cookies_file_path=final_cookie_file,
                    make_active=True
                )

                # Log session validation
                await self.services.database_service.log_session_validation(
                    session_id, True
                )

                await self._safe_edit_message(
                    status_message,
                    "✅ Session validated and stored successfully!\n\n"
                    "You can now use this bot to download Instagram content.\n"
                    "Use /session_list to manage your sessions."
                )

            except Exception as e:
                error_msg = str(e)
                await self._safe_edit_message(
                    status_message,
                    f"❌ Session validation failed: {error_msg}\n\n"
                    "Please ensure your cookies are valid and try again."
                )
                logger.error(f"Session validation failed for user {user.id}: {error_msg}")
                if temp_cookie_file.exists():
                    temp_cookie_file.unlink()

        except Exception as e:
            error_msg = str(e)
            await self._safe_edit_message(
                status_message,
                f"❌ Failed to process cookie file: {error_msg}"
            )
            logger.error(f"Cookie file processing failed for user {user.id}: {error_msg}")
            if temp_cookie_file.exists():
                temp_cookie_file.unlink()

    async def shutdown(self) -> None:
        """Shutdown with proper session cleanup."""
        try:
            # Update session usage before shutdown
            if hasattr(self, 'telegram_session_storage'):
                session = await self.telegram_session_storage.get_active_session()
                if session:
                    await self.telegram_session_storage.update_session_usage(session    ['id'])
            
            # Standard shutdown procedure
            shutdown_tasks = []
            
            if self.bot_app:
                if self.bot_app.updater:
                    shutdown_tasks.append(self.bot_app.updater.stop())
                shutdown_tasks.append(self.bot_app.stop())
                shutdown_tasks.append(self.bot_app.shutdown())
            
            if self.telethon_client:
                shutdown_tasks.append(self.telethon_client.disconnect())
            
            if self.services.database_service:
                shutdown_tasks.append(self.services.database_service.close())
            
            await asyncio.gather(*shutdown_tasks)
            logger.info("Bot shutdown complete with session preservation")
            
        except Exception as e:
            logger.error("Error during shutdown", error=str(e))

async def main() -> None:
    """
    Initialize and run the bot with optimized startup sequence.
    
    The startup sequence:
    1. Load configuration
    2. Create bot instance
    3. Initialize services
    4. Start bot application
    5. Configure cleanup jobs
    6. Wait for interruption
    
    The bot runs until interrupted by CTRL+C or system signal.
    All cleanup operations are handled in the shutdown sequence.
    """
    from src.core.load_config import load_configuration
    
    config = load_configuration()
    bot = EnhancedTelegramBot(config)
    
    try:
        # Initialize all components sequentially
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
        # Ensure proper cleanup on shutdown
        await bot.shutdown()

def run_bot() -> None:
    """
    Run the bot with proper event loop and comprehensive error handling.
    
    This function:
    1. Configures logging
    2. Sets up the asyncio event loop
    3. Runs the main bot function
    4. Handles interruptions and errors gracefully
    
    Raises:
        Exception: Re-raises any unhandled exceptions after logging
    """
    try:
        # Configure logging with timestamp and level information
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Run the bot in the asyncio event loop
        asyncio.run(main())
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        
    except Exception as e:
        # Log any unhandled exceptions
        logger.error(f"Bot error: {e}", exc_info=True)
        raise  # Re-raise the exception for proper error reporting

if __name__ == "__main__":
    run_bot()
