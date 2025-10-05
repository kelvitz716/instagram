#!/usr/bin/env python3
"""
Instagram Content Downloader Bot

A Telegram bot that automatically detects and downloads content from Instagram URLs.
Supports posts, reels, stories, highlights, and files with optimized performance
and service-based architecture.
"""

# Standard library imports
import asyncio
import json
import logging
import pathlib
import re
import sys
import time
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Third-party imports
import structlog
from rich.console import Console
from telegram import Message, Update, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, error as telegram_error
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telethon import TelegramClient
from telethon import errors as telethon_errors

# Core imports
from src.core.config import BotConfig
from src.core.services import BotServices
from src.core.session_commands import SessionCommands
from src.core.help_command import HelpCommandMixin
from src.core.resilience.retry import with_retry
from src.core.metrics_command import metrics_command
from src.core.resilience.circuit_breaker import with_circuit_breaker, ServiceUnavailableError
from src.core.resilience.recovery import SessionRecovery, StateRecovery
from src.core.telethon_auth_command import TelethonAuthCommand, LOGIN_OTP, LOGIN_PASSWORD
from src.core.session_manager import InstagramSessionManager
from src.core.constants import URL_PATTERN, CONTENT_ICONS
from src.core.monitoring.logging import setup_structured_logging

# Services
from src.services.database import DatabaseService
from src.services.session_storage import SessionStorageService
from src.services.telegram_session_storage import TelegramSessionStorage
from src.services.instagram_downloader import InstagramDownloader
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.progress import ProgressTracker
from src.services.cleanup import CleanupService

# Configure logger
logger = logging.getLogger(__name__)

# Service imports
from src.services.database import DatabaseService
from src.services.upload import FileUploadService
from src.services.bot_api_uploader import BotAPIUploader
from src.services.telethon_uploader import TelethonUploader
from src.services.instagram_downloader import InstagramDownloader
from src.services.progress import ProgressTracker
from src.services.session_storage import SessionStorageService, SessionStorageError
from src.services.telegram_session_storage import TelegramSessionStorage, TelegramSessionStorageError
from src.services.cleanup import CleanupService
from src.services.resource_manager import ResourceManager

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

# Import monitoring tools
from src.core.monitoring import setup_structured_logging
from src.core.config import LoggingConfig

# Initialize logging
logger = structlog.get_logger(__name__)
console = Console()

# Version information
BOT_VERSION = "3.0.0"

# Authentication states
LOGIN_OTP, LOGIN_PASSWORD = range(2)

class EnhancedTelegramBot(SessionCommands, HelpCommandMixin):
    def __init__(self, config: BotConfig):
        # Initialize bot with configuration
        self.config = config
        self.services = BotServices.create(config)
        self.content_detector = ContentDetector()
        self.session_manager = InstagramSessionManager(downloads_path=config.instagram.downloads_path)
        self.session_recovery = SessionRecovery(services=self.services)
        self.state_recovery = StateRecovery(services=self.services)
        self.session_commands = SessionCommands(session_manager=self.session_manager, services=self.services)
        # Initialize bot application
        self.bot_app = Application.builder().token(config.telegram.bot_token).build()
        # Initialize services
        self._init_services()
        # Setup command handlers
        self._setup_handlers()

    async def _initialize_database(self):
        """Initialize the database."""
        # Database is already initialized in BotServices.create()
        pass
    
    def _init_services(self):
        # Services are already initialized in BotServices.create()
        # Just assign the cleanup service from services
        self.cleanup_service = self.services.cleanup_service
        
    def _setup_handlers(self):
        # Configure bot command and message handlers
        # Add command handlers
        # Add command handlers with bot username for group chats
        self.bot_app.add_handler(CommandHandler("start", self._start_command))
        self.bot_app.add_handler(CommandHandler("help", self.handle_help))
        self.bot_app.add_handler(CommandHandler("metrics", metrics_command))
        self.bot_app.add_handler(CommandHandler("cleanup", self._cleanup_command))
        self.bot_app.add_handler(CommandHandler("stats", self._stats_command))
        self.bot_app.add_handler(CommandHandler("telegram_status", self._telegram_status_command))
        # Session management commands
        self.bot_app.add_handler(CommandHandler("session", self._session_command))
        self.bot_app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, self._session_command))
        self.bot_app.add_handler(CallbackQueryHandler(self.handle_session_button))
        
        # Add conversation handler for authentication
        auth_handler = ConversationHandler(
            entry_points=[CommandHandler("auth", self._auth_command)],
            states={
                LOGIN_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._otp_handler)],
                LOGIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._password_handler)]
            },
            fallbacks=[CommandHandler("cancel", self._cancel_auth)]
        )
        self.bot_app.add_handler(auth_handler)
        
        # Add URL detection handler for Instagram links
        self.bot_app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.Regex(r'https?://(?:www\.)?instagram\.com/'),
            self._handle_instagram_link
        ))
        
        # Add callback query handler
        self.bot_app.add_handler(CallbackQueryHandler(self._handle_callback))
        
        # Add error handler
        self.bot_app.add_error_handler(self._error_handler)
        
    async def initialize(self):
    # Initialize bot and all services
        try:
            # Initialize database first
            await self._initialize_database()
            
            # Start all other services
            await self.services.start_all()
            logger.info("Bot services initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize services", exc_info=True)
            raise
            
    async def shutdown(self):
    # Graceful shutdown of bot and services
        try:
            await self.services.stop_all()
            await self.bot_app.stop()
            await self.bot_app.shutdown()
            logger.info("Bot shutdown completed successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            
    def _schedule_cleanup(self):
        # Schedule periodic cleanup tasks
        cleanup_service = self.services.get(CleanupService)
        if cleanup_service:
            cleanup_service.schedule_cleanup(scheduler=self.bot_app)
            
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Handle /start command
        await update.message.reply_text(
            "👋 Welcome! Send me Instagram links and I'll download the content for you.\n"
            "Use /help to see all available commands."
        )
        
    @with_retry
    @with_circuit_breaker
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle incoming messages and detect Instagram URLs
        message = update.message
        text = message.text
        
        # Find all URLs in message
        urls = URL_PATTERN.finditer(text)
        instagram_urls = []
        
        for url_match in urls:
            url = url_match.group()
            if self.content_detector.is_instagram_url(url):
                instagram_urls.append(self.content_detector.normalize_url(url))
                
        if not instagram_urls:
            return
            
        # Process each Instagram URL
        for url in instagram_urls:
            try:
                content_type, identifier, secondary = self.content_detector.detect_content_type(url)
                await self._process_content(message, url, content_type, identifier, secondary, context)
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}", exc_info=True)
                await message.reply_text(f"Sorry, I couldn't process this URL: {url}")
                
    async def _process_content(self, message: Message, url: str, content_type: str, 
                             identifier: str, secondary: Optional[str], context: ContextTypes.DEFAULT_TYPE):
    # Process detected Instagram content
        progress_msg = await message.reply_text(
            f"{CONTENT_ICONS.get(content_type, '📄')} Processing {content_type}..."
        )
        
        try:
            downloader = self.services.get(InstagramDownloader)
            progress = self.services.get(ProgressTracker)
            
            # Start progress tracking
            tracker_id = progress.start_tracking(message.chat_id, message.message_id)
            
            # Download content
            files = await downloader.download(url, progress.update_progress)
            
            if not files:
                await progress_msg.edit_text("No content found or content is private.")
                return
                
            # Upload files
            for file in files:
                if file.stat().st_size > self.config.bot_api_limit:
                    await self._upload_large_file(message, file, context)
                else:
                    await self._upload_small_file(message, file, content_type)
                    
            await progress_msg.delete()
            
        except Exception as e:
            error_msg = f"Failed to process {content_type}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            await progress_msg.edit_text(error_msg)
            
    async def _upload_large_file(self, message: Message, file: Path, context: ContextTypes.DEFAULT_TYPE, caption: str = None):
        # Upload large files using Telethon
        uploader = self.services.get(TelethonUploader)
        await uploader.upload(file, caption=caption)
        
    async def _upload_small_file(self, message: Message, file: Path, content_type: str, caption: str = None):
        # Upload small files using Bot API
        uploader = self.services.get(BotAPIUploader)
        await uploader.upload(file, caption=caption)
        
    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE):
    # Handle bot errors
        try:
            if update and isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    "Sorry, something went wrong. Please try again later."
                )
            logger.error("Bot error", exc_info=context.error)
        except:
            logger.exception("Error in error handler")
            
    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle callback queries from inline keyboards
        query = update.callback_query
        await query.answer()
        
        try:
            action, data = query.data.split(':', 1)
            if action == 'auth':
                await self._handle_auth_callback(query, data)
            elif action == 'cancel':
                await query.message.edit_text("Operation cancelled.")
        except Exception as e:
            logger.error(f"Error handling callback: {e}", exc_info=True)
            await query.message.edit_text("Sorry, something went wrong.")
            
    async def _handle_auth_callback(self, query: CallbackQuery, data: str):
        """Handle authentication callbacks."""
        pass
        
    async def _telegram_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /telegram_status command."""
        try:
            response = await context.bot.get_me()
            await update.message.reply_text(
                "📡 *Bot Status*\n\n"
                f"Bot API: ✅ Connected\n"
                f"Username: @{response.username}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error("Telegram status check failed", exc_info=e)
            await update.message.reply_text("❌ Bot status check failed")
            
    async def _session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /session command and file uploads."""
        try:
            await self.session_commands.handle_session(update, context)
        except Exception as e:
            logger.error("Session command error", exc_info=e)
            await update.message.reply_text(
                "❌ An error occurred while processing your request. Please try again."
            )
            
    async def _auth_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle /auth command to start authentication process
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Start Authentication", callback_data='auth:start')],
            [InlineKeyboardButton("Cancel", callback_data='cancel')]
        ])
        await update.message.reply_text(
            "Start Instagram authentication process:",
            reply_markup=keyboard
        )
        return ConversationHandler.END
        
    async def _otp_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Handle OTP code entry
        otp_code = update.message.text.strip()
        
        try:
            # Verify OTP code
            await self.session_manager.verify_otp(otp_code)
            await update.message.reply_text("Authentication successful! ✅")
            return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text(f"Invalid OTP code. Please try again.\nError: {str(e)}")
            return LOGIN_OTP
            
    async def _password_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle password entry"""
        password = update.message.text.strip()
        
        try:
            # Attempt password login
            await self.session_manager.login_with_password(password)
            await update.message.reply_text("Login successful! ✅")
            return ConversationHandler.END
        except Exception as e:
            await update.message.reply_text(f"Login failed: {str(e)}")
            return ConversationHandler.END
            
    async def _handle_instagram_link(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle Instagram links in messages."""
        if not update.message or not update.message.text:
            return
            
        try:
            # Send initial status
            status_msg = await update.message.reply_text(
                "🔄 Processing Instagram link..."
            )

            url = update.message.text.strip()
            downloaded_files = await self.services.instagram_service.download_content(url)
            if not downloaded_files:
                await status_msg.edit_text("❌ Download failed: No content found")
                return

            # Try to extract metadata from the first file
            meta = {}
            try:
                meta = await self.services.instagram_service._extract_metadata(downloaded_files[0])
            except Exception as e:
                logger.warning(f"Metadata extraction failed: {e}")

            media_count = len(downloaded_files)
            caption = meta.get('caption', '').strip() or 'Instagram Post'
            username = meta.get('username', '')
            post_url = meta.get('url', url)

            # Announce post processed and counts
            await status_msg.edit_text(
                f"📷 Post processed!\n"
                f"📥 Downloaded: {media_count} files\n"
                f"📤 Uploaded: 0/{media_count} files\n"
                f"⬆️ Uploading to Telegram..."
            )

            # Send summary message before media
            summary_caption = (
                f"📷 Instagram Post\n\n"
                f"{caption}\n\n"
                f"📱 Total media: {media_count}\n\n"
                f"🔗 {post_url}\n\n"
                f"📌 Media 1/{media_count}"
            )

            upload_count = 0
            for idx, file_path in enumerate(downloaded_files, 1):
                file_size = file_path.stat().st_size
                mime_type = "video/mp4" if file_path.suffix.lower() == '.mp4' else "image/jpeg"
                is_first = idx == 1

                # Prepare caption
                caption = summary_caption if is_first else f"Media {idx}/{media_count} - Part of post"
                
                if file_size > 50 * 1024 * 1024:
                    await self._upload_large_file(update.message, file_path, context, caption)
                else:
                    await self._upload_small_file(update.message, file_path, mime_type, caption)
                upload_count += 1
                
                # Update progress every 3rd file or on last file
                if idx % 3 == 0 or idx == media_count:
                    await status_msg.edit_text(
                        f"📷 Post processed!\n"
                        f"📥 Downloaded: {media_count} files\n"
                        f"📤 Uploaded: {upload_count}/{media_count} files\n"
                        f"⬆️ Uploading to Telegram..."
                    )

            # Final summary
            await update.message.reply_text(
                f"📷 Post processed!\n"
                f"📥 Downloaded: {media_count} files\n"
                f"📤 Uploaded: {upload_count}/{media_count} files\n"
                f"🎉 All files uploaded successfully!"
            )

            await status_msg.delete()

        except Exception as e:
            logger.error(f"Error processing Instagram link: {e}", exc_info=True)
            try:
                await update.message.reply_text(
                    f"❌ Failed to process Instagram content:\n{str(e)}\n\n"
                    "Please make sure you have a valid Instagram session. "
                    "Use /session to upload a cookies.txt file."
                )
            except:
                pass
        except Exception as e:
            await update.message.reply_text(f"Login failed. Please try again.\nError: {str(e)}")
            return LOGIN_PASSWORD
            
    async def _cancel_auth(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Cancel the authentication process
        await update.message.reply_text("Authentication cancelled.")
        return ConversationHandler.END

    async def _cleanup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /cleanup command."""
        try:
            cleanup_service = self.services.get(CleanupService)
            if not cleanup_service:
                await update.message.reply_text("Cleanup service not available.")
                return
                
            dirs_removed, bytes_freed = await asyncio.to_thread(cleanup_service.cleanup_old_directories)
            mb_freed = bytes_freed / (1024 * 1024)
            
            await update.message.reply_text(
                f"Cleanup completed!\n"
                f"✨ Removed: {dirs_removed} directories\n"
                f"🗑 Freed up: {mb_freed:.2f} MB"
            )
        except Exception as e:
            logger.error("Cleanup error", exc_info=e)
            await update.message.reply_text(f"Error during cleanup: {str(e)}")

    async def _stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        try:
            cleanup_service = self.services.get(CleanupService)
            if not cleanup_service:
                await update.message.reply_text("Statistics not available.")
                return
                
            stats = await asyncio.to_thread(cleanup_service.get_storage_stats)
            
            await update.message.reply_text(
                f"📊 STORAGE STATISTICS\n\n"
                f"💾 Total Size: {stats['total_size_mb']:.2f} MB\n"
                f"📁 Total Directories: {stats['total_directories']}\n"
                f"🆕 Active Directories: {stats['clean_directories']}\n"
                f"⏳ Old Directories: {stats['old_directories']}"
            )
        except Exception as e:
            logger.error("Stats error", exc_info=e)
            await update.message.reply_text(f"Error getting statistics: {str(e)}")

    async def _telegram_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /telegram_status command."""
        try:
            # Check basic bot connectivity
            response = await context.bot.get_me()
            
            # Check Telethon client if available
            telethon_status = "✅ Available"
            if hasattr(self, 'telethon_client'):
                try:
                    telethon_connected = await self.telethon_client.is_connected()
                    telethon_status = "✅ Connected" if telethon_connected else "❌ Not Connected"
                except:
                    telethon_status = "❌ Error"
            else:
                telethon_status = "⚠️ Not Configured"
            
            # Send status message
            status_text = (
                "📡 *Bot Status*\n\n"
                f"Bot API: ✅ Connected\n"
                f"Username: @{response.username}\n"
                f"Large File Upload: {telethon_status}"
            )
            await update.message.reply_text(status_text, parse_mode='Markdown')
        except Exception as e:
            logger.error("Telegram status check failed", exc_info=e)
            await update.message.reply_text("❌ Bot status check failed")
            
    async def _session_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /session command and file uploads."""
        try:
            await self.session_commands.handle_session(update, context)
        except Exception as e:
            logger.error("Session command error", exc_info=e)
            await update.message.reply_text(
                "❌ An error occurred while processing your request. Please try again."
            )

    async def _session_list_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /session_list command."""
        try:
            await self.session_commands.handle_session_list(update, context)
        except Exception as e:
            logger.error("Session list error", exc_info=e)
            await update.message.reply_text(
                "❌ An error occurred while checking session status. Please try again."
            )

# Instagram URL constants
BASE_INSTAGRAM = r'(?:https?://)?(?:www\.)?'
INSTAGRAM_DOMAINS = ['instagram.com', 'instagr.am']
PATH_END = r'(?:/|\?|&|$)'

# Instagram URL pattern for basic validation
INSTAGRAM_URL_PATTERN = re.compile(
    f"{BASE_INSTAGRAM}(?:{'|'.join(INSTAGRAM_DOMAINS)})/.*",
    re.IGNORECASE
)

class ContentDetector:
    # Enhanced content detection for Instagram URLs with pattern matching
    
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
        # Detect Instagram content type from URL
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
        # Check if URL is a valid Instagram URL
        return bool(INSTAGRAM_URL_PATTERN.match(url))
    
    @classmethod
    def normalize_url(cls, url: str) -> str:
    # Normalize Instagram URL by removing unnecessary parameters
        # Remove query parameters except essential ones for stories
        if '/stories/' in url:
            return url.split('?')[0]
        
        # For other content, remove query params and trailing slash
        url = url.split('?')[0].rstrip('/')
        
        # Normalize domain
        url = url.replace('instagr.am', 'instagram.com')
        url = url.replace('http://', 'https://')
        
        return url

# Second implementation removed to fix duplicate class definition
        
        # Initialize recovery services
        self.session_recovery = SessionRecovery(self.services)
        self.state_recovery = StateRecovery(self.services)
        
        # Initialize bot application and handlers
        self._init_services()
        self._setup_handlers()
        
    def _setup_directories(self) -> None:
    # Setup required directories with proper permissions
        try:
            for path in [self.config.downloads_path, self.config.uploads_path, self.config.temp_path]:
                path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Failed to create directories: {e}")
            raise
            
    @lru_cache(maxsize=1)
    def _get_uploader(self, file_size: int) -> str:
    # Get the appropriate uploader based on file size
        return 'telethon' if file_size > self.config.upload.large_file_threshold else 'bot_api'

    def _setup_handlers(self) -> None:
    # Set up command handlers and message handlers
        # Core command handlers
        self.bot_app.add_handler(CommandHandler("start", self._start_command))
        self.bot_app.add_handler(CommandHandler("help", self.help_command))
        self.bot_app.add_handler(CommandHandler("metrics", metrics_command))
        
        # Session management handlers
        self.bot_app.add_handler(CommandHandler("session_upload", self.handle_session_upload))
        self.bot_app.add_handler(CommandHandler("session_list", self.handle_session_list))
        self.bot_app.add_handler(
            MessageHandler(filters.Document.ALL & ~filters.COMMAND, self.handle_session_upload)
        )
        self.bot_app.add_handler(
            CallbackQueryHandler(
                self.handle_session_button,
                pattern=r'^(activate|delete)_session_\d+$'
            )
        )
        self.bot_app.add_handler(
            MessageHandler(filters.Document.ALL & ~filters.COMMAND, self.handle_session_upload)
        )
        self.bot_app.add_handler(
            CallbackQueryHandler(
                self.handle_session_button, 
                pattern=r'^(activate|delete)_session_\d+$'
            )
        )

        # URL handling for Instagram links
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

    async def initialize(self) -> None:
    # Initialize the bot and all its services
        try:
            # Initialize components sequentially
            await self._initialize_database()
            await self._initialize_telegram()
            self._initialize_instagram()
            await self._initialize_uploaders()

            logger.info("Bot initialized successfully")

        except Exception as e:
            logger.error("Failed to initialize bot", error=str(e))
            raise

    async def _initialize_database(self) -> None:
    # Initialize database connection and schema
        if self.services.database_service:
            try:
                await self.services.database_service.initialize()
                logger.info("Database initialized successfully")
            except Exception as e:
                logger.error("Failed to initialize database", exc_info=True)
                raise

    async def _initialize_telegram(self) -> None:
    # Initialize Telegram bot application
        try:
            # Create Telegram bot application
            self.bot_app = Application.builder().token(self.config.telegram.bot_token).build()
            # Set up handlers
            self._setup_handlers()
            logger.info("Telegram bot initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Telegram bot", exc_info=True)
            raise
            
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Handle /start command
        await update.message.reply_text(
            "👋 Welcome! Send me Instagram links and I'll download the content for you.\n"
            "Use /help to see all available commands."
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # Handle /help command
        help_text = (
            "📚 *Available Commands*\n\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/metrics - Show bot statistics\n"
            "/session_upload - Upload a new Instagram session\n"
            "/session_list - List all saved sessions\n\n"
            "Just send me an Instagram link and I'll download it for you!\n\n"
            "*Supported Content*:"
            "\n- Posts (photos/videos)"
            "\n- Stories"
            "\n- Reels"
            "\n- IGTV Videos"
            "\n- Profile Pictures"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
        
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Handle messages containing Instagram URLs
        message = update.message or update.channel_post
        if not message:
            return
            
        text = message.text or message.caption or ""
        urls = re.findall(INSTAGRAM_URL_PATTERN, text)
        
        if not urls:
            return
            
        status_message = await message.reply_text("Processing Instagram URL(s)...")
        
        try:
            for url in urls:
                try:
                    # Download the content
                    files = await self.services.instagram_service.download_post(url)
                    if not files:
                        await status_message.edit_text(f"❌ No content found for URL: {url}")
                        continue
                        
                    await status_message.edit_text(f"📥 Downloading content from: {url}")
                    
                    # Upload each file
                    for file_path in files:
                        try:
                            await self.services.file_service.upload_file(
                                file_path,
                                message.chat_id,
                                progress_callback=lambda p: status_message.edit_text(f"⬆️ Uploading... {p}%")
                            )
                        except Exception as e:
                            logger.error(f"Failed to upload file {file_path}: {e}")
                            await status_message.edit_text(f"❌ Failed to upload content: {str(e)}")
                            
                except Exception as e:
                    logger.error(f"Failed to process URL {url}: {e}")
                    await status_message.edit_text(f"❌ Failed to process URL {url}: {str(e)}")
                    
            await status_message.edit_text("✅ All URLs processed!")
            
        except Exception as e:
            logger.error(f"Error in handle_message: {e}")
            await status_message.edit_text(f"❌ An error occurred: {str(e)}")

    def _initialize_instagram(self) -> None:
    # Initialize Instagram services
        try:
            # Instagram service is already initialized in the constructor
            if self.services.instagram_service:
                logger.info("Instagram service initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize Instagram service", exc_info=True)
            raise
            
    async def _initialize_uploaders(self) -> None:
    # Initialize file upload services
        try:
            if self.services.file_service:
                # File service is already initialized in the constructor
                logger.info("Upload services initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize upload services", exc_info=True)
            raise

    async def shutdown(self) -> None:
    # Shutdown the bot gracefully
        try:
            if hasattr(self, 'bot_app'):
                await self.bot_app.stop()
            if hasattr(self, 'services'):
                await self.services.cleanup()
            logger.info("Bot shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

def main() -> int:
    # Main entry point for the bot.
    from src.core.load_config import load_configuration
    
    try:
        # Load configuration first
        config = load_configuration()
        
        # Set up structured logging with the bot's logging config
        setup_structured_logging(config.logging)
        logger = structlog.get_logger(__name__)
        
        # Create bot instance with configuration
        bot = EnhancedTelegramBot(config)
        
        # Run the bot
        asyncio.run(run_bot(bot))
        return 0
        
    except Exception as e:
        # Get logger for error reporting
        logger = structlog.get_logger(__name__)
        # Log error with exception info
        logger.exception("Fatal error in main loop")
        return 1

async def run_bot(bot: 'EnhancedTelegramBot') -> None:
    # Initialize and run the bot with optimized startup sequence.
    logger = structlog.get_logger(__name__)
    
    try:
        # Initialize all components sequentially
        logger.info("Initializing bot components...")
        await bot.initialize()
        await bot.bot_app.initialize()
        await bot.bot_app.start()
        await bot.bot_app.updater.start_polling()
        
        # Schedule cleanup after bot is fully initialized
        bot._schedule_cleanup()
        logger.info("Bot started successfully")
        
        # Keep the bot running until interrupted
        stop_event = asyncio.Event()
        await stop_event.wait()
        
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Bot stopping due to interrupt")
    except Exception as e:
        logger.error("Error during bot operation", exc_info=True)
        raise
    finally:
        # Ensure proper cleanup on shutdown
        logger.info("Shutting down bot...")
        await bot.shutdown()
        logger.info("Bot shutdown complete")

def run_bot_cli() -> None:
    # Command-line entry point to run the bot. Configures basic logging and runs the main function.
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger = structlog.get_logger(__name__)
        logger.info("Bot stopped by user")
        sys.exit(0)

if __name__ == "__main__":
    run_bot_cli()