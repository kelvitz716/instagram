#!/usr/bin/env python3
"""
Enhanced Telegram Bot with third-party libraries for better efficiency and maintainability.
"""

import asyncio
import sys
import os
import logging
from asyncio import Lock
from pathlib import Path
from typing import Optional, List
import contextlib
import threading
import time

# Third-party imports for enhanced functionality
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import aiofiles
from tqdm.asyncio import tqdm
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
import magic
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import aiosqlite
from asyncio_throttle import Throttler

# Telegram imports
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, NetworkError, TimedOut, RetryAfter
from telethon import TelegramClient
from telethon.errors import FloodWaitError
import instaloader


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

BOT_VERSION = "1.0.0"

# Resource limits
BOT_API_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB limit for Bot API
TELETHON_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit for Telethon
MAX_MEMORY_USAGE_PER_FILE = 100 * 1024 * 1024  # 100MB max memory per file


class BotSettings(BaseSettings):
    """Configuration management using Pydantic Settings."""

    # Required settings
    bot_token: str = Field(..., env='BOT_TOKEN', description="Telegram Bot Token")
    api_id: int = Field(..., env='API_ID', description="Telegram API ID")
    api_hash: str = Field(..., env='API_HASH', description="Telegram API Hash")
    target_chat_id: int = Field(..., env='TARGET_CHAT_ID', description="Target Chat ID")
    phone_number: Optional[str] = Field(None, env='PHONE_NUMBER', description="Phone number for Telethon login")

    # Optional settings with defaults
    downloads_path: str = Field('Downloads', env='DOWNLOADS_PATH', description="Downloads directory")
    max_concurrent_uploads: int = Field(3, env='MAX_CONCURRENT_UPLOADS', description="Max concurrent uploads")
    upload_rate_limit: int = Field(5, env='UPLOAD_RATE_LIMIT', description="Uploads per second limit")
    database_path: str = Field('bot_data.db', env='DATABASE_PATH', description="Database file path")

    # Additional optional settings from .env
    log_level: str = Field('INFO', env='LOG_LEVEL', description="Logging level")
    log_file: Optional[str] = Field(None, env='LOG_FILE', description="Log file path")
    session_name: str = Field('enhanced_session', env='SESSION_NAME', description="Telethon session name")
    auto_watch_files: bool = Field(False, env='AUTO_WATCH_FILES', description="Enable automatic file watching")
    large_file_threshold: int = Field(52428800, env='LARGE_FILE_THRESHOLD', description="File size threshold for Telethon")
    max_retry_attempts: int = Field(3, env='MAX_RETRY_ATTEMPTS', description="Maximum retry attempts")
    # Batching / worker tuning
    batch_size: int = Field(10, env='BATCH_SIZE', description="Max files per batch for enqueuing")
    bot_api_pause_seconds: float = Field(3.0, env='BOT_API_PAUSE_SECONDS', description="Pause after each Bot API upload (seconds)")
    telethon_pause_seconds: float = Field(1.0, env='TELETHON_PAUSE_SECONDS', description="Pause after each Telethon upload (seconds)")

    status_update_interval: float = Field(5.0, env='STATUS_UPDATE_INTERVAL', description="Minimum seconds between status updates")
    status_max_retries: int = Field(3, env='STATUS_MAX_RETRIES', description="Maximum retries for status message updates")

    @field_validator('target_chat_id', 'api_id', 'max_concurrent_uploads', 'upload_rate_limit', 'large_file_threshold', 'max_retry_attempts')
    @classmethod
    def validate_integers(cls, v):
        if not isinstance(v, int):
            raise ValueError('Must be an integer')
        return v

    @field_validator('auto_watch_files', mode="before")
    @classmethod
    def validate_boolean(cls, v):
        if isinstance(v, str):
            return v.lower() in ('true', '1', 'yes', 'on')
        return bool(v)

    class Config:
        env_file = '.env'
        env_file_encoding = 'utf-8'


class DatabaseManager:
    """Async database manager for bot statistics and state."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._conn_lock = asyncio.Lock()

    async def initialize(self):
        """Initialize database tables and open persistent connection."""
        try:
            self._conn = await aiosqlite.connect(self.db_path)
            await self._conn.execute('''
                CREATE TABLE IF NOT EXISTS file_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    upload_method TEXT NOT NULL,
                    success BOOLEAN NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            ''')
            await self._conn.commit()
            logger.info("Database initialized successfully", db_path=self.db_path)
        except Exception as e:
            logger.error("Failed to initialize database", error=str(e), db_path=self.db_path)
            # Create a fallback in-memory database
            try:
                self._conn = await aiosqlite.connect(":memory:")
                await self._conn.execute('''CREATE TABLE file_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, file_size INTEGER,
                    upload_method TEXT, success BOOLEAN, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT)''')
                logger.warning("Using in-memory database as fallback")
            except Exception as fallback_error:
                logger.critical("Failed to create fallback database", error=str(fallback_error))
                self._conn = None
               
    async def _ensure_connection(self) -> bool:
        """Ensure database connection is valid, recreate if needed."""
        if not self._conn:
            logger.warning("Database connection lost, attempting to reconnect")
            try:
                await self.initialize()
                return self._conn is not None
            except Exception as e:
                logger.error("Failed to reconnect to database", error=str(e))
                return False
        return True

    async def log_file_operation(self, filename: str, file_size: int, method: str,
                                 success: bool, error_msg: Optional[str] = None):
        """Log a file operation to database."""
        if not await self._ensure_connection():
            logger.warning("Database unavailable, skipping log operation", filename=filename)
            return
            
        try:
            async with self._conn_lock:
                await self._conn.execute('''
                    INSERT INTO file_stats (filename, file_size, upload_method, success, error_message)
                    VALUES (?, ?, ?, ?, ?)
                ''', (filename, file_size, method, success, error_msg))
                await self._conn.commit()
        except Exception as e:
            logger.error("Failed to log file operation to database", error=str(e), filename=filename)
            # Don't re-raise to avoid breaking the main flow

    async def get_statistics(self) -> dict:
        """Get bot statistics from database."""
        if not await self._ensure_connection():
            logger.warning("Database unavailable, returning zero statistics")
            return {'total_files': 0, 'successful': 0, 'failed': 0, 'total_bytes_sent': 0}
            
        try:
            async with self._conn_lock:
                async with self._conn.execute('''
                    SELECT 
                        COUNT(*) as total_files,
                        SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                        SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as failed,
                        SUM(CASE WHEN success = 1 THEN file_size ELSE 0 END) as total_bytes_sent
                    FROM file_stats
                ''') as cursor:
                    row = await cursor.fetchone()
                    return {
                        'total_files': row[0] or 0,
                        'successful': row[1] or 0,
                        'failed': row[2] or 0,
                        'total_bytes_sent': row[3] or 0
                    }
        except Exception as e:
            logger.error("Failed to get statistics from database", error=str(e))
            # Return default statistics instead of crashing
            return {'total_files': 0, 'successful': 0, 'failed': 0, 'total_bytes_sent': 0}

    async def close(self):
        """Close DB connection."""
        try:
            if self._conn:
                # Ensure all pending operations are committed
                await self._conn.commit()
                await self._conn.close()
                logger.info("Database connection closed successfully")
        except Exception as e:
            logger.error("Error closing database connection", error=str(e))
        finally:
            self._conn = None
       
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

class FileWatcher(FileSystemEventHandler):
    """Watch Downloads directory for new files and trigger callback."""

    def __init__(self, callback, loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop
        self.supported_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
            '.pdf', '.doc', '.docx', '.txt', '.zip', '.rar', '.7z',
            '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'
        }

    def on_created(self, event):
        if not event.is_directory:
            file_path = Path(event.src_path)
            if file_path.suffix.lower() in self.supported_extensions:
                logger.info("New media file detected", filename=file_path.name)
                # Use run_coroutine_threadsafe because watchdog event handler runs in separate thread
                asyncio.run_coroutine_threadsafe(self._process_when_ready(file_path), self.loop)

    async def _process_when_ready(self, file_path: Path, timeout=30, poll_interval=1):
        """
        Wait for file to be fully written before processing.
        Checks if file size remains stable for `poll_interval` seconds within `timeout`.
        """
        start = time.time()
        last_size = -1
        while time.time() - start < timeout:
            try:
                current_size = file_path.stat().st_size
                if current_size == last_size:
                    await self.callback(file_path)
                    return
                last_size = current_size
            except FileNotFoundError:
                # File may have been removed before processing
                logger.warning("File disappeared before processing", filename=file_path.name)
                return
            await asyncio.sleep(poll_interval)
        logger.warning("File not stable for processing (timeout)", filename=file_path.name)


class EnhancedTelegramBot:
    """Enhanced Telegram bot with third-party library integrations."""

    def __init__(self, settings: BotSettings):
        self.settings = settings
        self.downloads_path = Path(settings.downloads_path)

        # Initialize components
        self.db = DatabaseManager(settings.database_path)
        self.throttler = Throttler(rate_limit=settings.upload_rate_limit)

        # Telegram clients
        self.bot_app: Optional[Application] = None
        self.telethon_client: Optional[TelegramClient] = None
        self._telethon_upload_semaphore = asyncio.Semaphore(self.settings.max_concurrent_uploads)

        # File watcher
        self.observer: Optional[Observer] = None
        self.is_watching = False  # Track watcher state

        # Thread safety locks
        self._counter_lock = Lock()

        # asyncio event loop reference (set during initialize)
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        # Queues for Bot API and Telethon uploads
        self.bot_api_queue: "asyncio.Queue[Path]" = asyncio.Queue()
        self.telethon_queue: "asyncio.Queue[Path]" = asyncio.Queue()

        # Worker tasks (created on initialize)
        self._bot_api_worker_task: Optional[asyncio.Task] = None
        self._telethon_worker_task: Optional[asyncio.Task] = None

        # Tracking counters for progress and active uploads
        self._completed_count: int = 0
        self._total_to_process: int = 0
        self._failed_count: int = 0
        self._current_upload_count: int = 0
        self._total_media_count: int = 0
        self._active_uploads: int = 0

        # File numbering for single file processing
        self._single_file_counter: int = 0
        self._single_file_counter_lock = asyncio.Lock()
         
        # Pauses (seconds) between uploads to respect rate limits
        self._bot_api_pause = float(self.settings.bot_api_pause_seconds)
        self._telethon_pause = float(self.settings.telethon_pause_seconds)
        self._batch_size = int(self.settings.batch_size)

    async def _increment_completed(self):
        """Thread-safe increment of completed counter."""
        async with self._counter_lock:
            self._completed_count += 1
            
    async def _increment_failed(self):
        """Thread-safe increment of failed counter."""
        async with self._counter_lock:
            self._failed_count += 1
            
    async def _increment_active_uploads(self):
        """Thread-safe increment of active uploads counter."""
        async with self._counter_lock:
            self._active_uploads += 1
            
    async def _decrement_active_uploads(self):
        """Thread-safe decrement of active uploads counter."""
        async with self._counter_lock:
            self._active_uploads -= 1
            
    async def _get_counters(self) -> tuple[int, int, int]:
        """Thread-safe getter for all counters."""
        async with self._counter_lock:
            return self._completed_count, self._failed_count, self._active_uploads
            
    async def _reset_counters(self):
        """Thread-safe reset of processing counters."""
        async with self._counter_lock:
            self._completed_count = 0
            self._failed_count = 0
            self._active_uploads = 0

    async def initialize(self):
        """Initialize all bot components."""
        logger.info("Initializing enhanced Telegram bot", version=BOT_VERSION)

        # Configure logging level
        log_level = getattr(logging, self.settings.log_level.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
        structlog.get_logger().setLevel(log_level)

        # Initialize database
        await self.db.initialize()

        # Initialize Telegram clients
        self.bot_app = Application.builder().token(self.settings.bot_token).build()
        self._setup_handlers()

        self.telethon_client = TelegramClient(
            self.settings.session_name,
            self.settings.api_id,
            self.settings.api_hash
        )
        await self.telethon_client.start(phone=self.settings.phone_number)

        # Create downloads directory
        self.downloads_path.mkdir(exist_ok=True)

        # Setup file watcher with proper event loop
        self.loop = asyncio.get_running_loop()
        event_handler = FileWatcher(self.process_single_file, self.loop)
        self._counter_lock = Lock()  # Reinitialize the counter lock with proper event loop
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.downloads_path), recursive=True)

        # Start queue workers
        # create background workers to process bot api and telethon queues
        if self._bot_api_worker_task is None:
            self._bot_api_worker_task = asyncio.create_task(self._bot_api_worker(), name="bot_api_worker")
        if self._telethon_worker_task is None:
            self._telethon_worker_task = asyncio.create_task(self._telethon_worker(), name="telethon_worker")

        logger.info("Bot initialization complete",
                    auto_watch=self.settings.auto_watch_files,
                    downloads_path=str(self.downloads_path))

    def _setup_handlers(self):
        """Setup command handlers."""
        self.bot_app.add_handler(CommandHandler("start", self.handle_start))
        self.bot_app.add_handler(CommandHandler("sendmedia", self.handle_sendmedia))
        self.bot_app.add_handler(CommandHandler("stats", self.handle_stats))
        self.bot_app.add_handler(CommandHandler("watch", self.handle_watch_toggle))
        self.bot_app.add_handler(CommandHandler("downloadig", self.handle_download_instagram))
 
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        await update.message.reply_text(
            f"🤖 **Enhanced Telegram Media Bot v{BOT_VERSION}**\n\n"
            "Commands:\n"
            "• `/sendmedia` - Process all files in Downloads\n"
            "• `/stats` - Show detailed statistics\n"
            "• `/watch` - Toggle automatic file watching\n"
            "• `/downloadig <url>` - Download a single Instagram post\n"
            "• `/start` - Show this help\n\n"
            "Features: Smart file handling, automatic watching, detailed logging",
            parse_mode='Markdown'
        )

    async def handle_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

        """Show enhanced statistics."""
        stats = await self.db.get_statistics()
        files_waiting = len(self._find_media_files())

        success_rate = (stats['successful'] / max(stats['total_files'], 1)) * 100

        stats_text = f"""📊 **Bot Statistics**

📁 Total files processed: `{stats['total_files']}`
✅ Successfully sent: `{stats['successful']}`
❌ Failed: `{stats['failed']}`
📊 Success rate: `{success_rate:.1f}%`
💾 Total data sent: `{self._format_bytes(stats['total_bytes_sent'])}`
🔍 Files waiting: `{files_waiting}`"""

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def handle_watch_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Toggle file watching."""
        if self.observer is None:
            await update.message.reply_text("⚠️ File watcher not initialized.")
            return

        if self.is_watching and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
            self.is_watching = False
            logger.info("File watching disabled by user")
            await update.message.reply_text("🔍 File watching disabled")
        else:
            self.observer = Observer()
            event_handler = FileWatcher(self.process_single_file, self.loop)
            self.observer.schedule(event_handler, str(self.downloads_path), recursive=True)
            self.observer.start()
            self.is_watching = True
            logger.info("File watching enabled by user")
            await update.message.reply_text("👁️ File watching enabled - new files will be processed automatically")

    async def handle_sendmedia(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Process media files in batches with enhanced progress tracking."""
        logger.info("Processing sendmedia command", user_id=update.effective_user.id)

        files = self._find_media_files()
        if not files:
            await update.message.reply_text("📂 No media files found")
            return

        total_files = len(files)
        status_msg = await update.message.reply_text(
            f"🔍 Found {total_files} files. Processing in batches of {self._batch_size}..."
        )

        # Reset counters safely
        await self._reset_counters()
        current_batch = 1
        total_batches = (total_files + self._batch_size - 1) // self._batch_size

        for i in range(0, total_files, self._batch_size):
            batch = files[i:i + self._batch_size]
            batch_size = len(batch)

            completed, failed, active = await self._get_counters()
            await status_msg.edit_text(
                f"📤 Processing Batch {current_batch}/{total_batches}\n"
                f"• Total files: {total_files}\n"
                f"• Current batch: {batch_size} files\n"
                f"• Completed: {completed}/{total_files}\n"
                f"• Active uploads: {active}"
            )

            for idx, file_path in enumerate(batch, 1):
                try:
                    file_size = file_path.stat().st_size
                    file_number = i + idx

                    if file_size <= self.settings.large_file_threshold:
                        await self.bot_api_queue.put((file_path, file_number, total_files))
                    else:
                        await self.telethon_queue.put((file_path, file_number, total_files))

                except FileNotFoundError:
                    logger.warning("File disappeared", filename=file_path.name)
                    await self._increment_failed()

            # Wait for current batch to complete
            completed, failed, active = await self._get_counters()
            while (not self.bot_api_queue.empty() or
                not self.telethon_queue.empty() or
                active > 0):
                await asyncio.sleep(1)
                completed, failed, active = await self._get_counters()

            current_batch += 1

        # Final summary
        completed, failed, active = await self._get_counters()
        success_rate = (completed / total_files) * 100 if total_files > 0 else 0
        final_message = (
            f"✅ Upload Complete!\n\n"
            f"📊 Summary:\n"
            f"• Total files processed: {total_files}\n"
            f"• Successfully sent: {completed}\n"
            f"• Failed: {failed}\n"
            f"• Success rate: {success_rate:.1f}%"
        )
        await status_msg.edit_text(final_message)

    async def _get_next_file_number(self) -> int:
        """Thread-safe method to get the next file number for single file processing."""
        async with self._single_file_counter_lock:
            self._single_file_counter += 1
            return self._single_file_counter

    async def _reset_single_file_counter(self):
        """Reset the single file counter (useful for batch operations)."""
        async with self._single_file_counter_lock:
            self._single_file_counter = 0

    async def handle_download_instagram(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Handles the /downloadig command to download a single Instagram post.
        The downloaded file is then automatically added to the bot's processing queue.
        """
        if not context.args or "instagram.com" not in context.args[0]:
            await update.message.reply_text("Usage: /downloadig <instagram_url>")
            return

        url = context.args[0]
        status_msg = await update.message.reply_text(f"⏳ Starting download for: `{url}`")
        logger.info("Received Instagram download request", url=url)

        try:
            # Get files before download to compare later
            files_before = set(self._get_all_files_in_directory(self.downloads_path))
            
            # Run the blocking Instaloader download function in a separate thread
            download_result = await asyncio.to_thread(self._download_instagram_post, url)

            if download_result["success"]:
                logger.info("Instagram download successful", downloaded_files=download_result["files"])
                await status_msg.edit_text("✅ Download successful! Processing files...")

                # Get files after download
                files_after = set(self._get_all_files_in_directory(self.downloads_path))
                newly_downloaded_files = list(files_after - files_before)

                if newly_downloaded_files:
                    logger.info("Found newly downloaded files", count=len(newly_downloaded_files), files=[f.name for f in newly_downloaded_files])
                    processed_count = 0
                    for file_path in newly_downloaded_files:
                        if file_path.suffix.lower() in self._get_supported_extensions():
                            await self.process_single_file(file_path)
                            processed_count += 1
                        else:
                            logger.info("Skipping unsupported file", filename=file_path.name)

                    if processed_count > 0:
                        await status_msg.edit_text(f"✅ Download and upload complete! Processed {processed_count} files.")
                    else:
                        await status_msg.edit_text("✅ Download complete, but no supported media files found.")
                else:
                    logger.warning("No new files found after download", 
                                files_before=len(files_before), files_after=len(files_after))
                    await status_msg.edit_text("❌ No new files found after download. The content may already exist or download failed.")
            else:
                error_msg = download_result.get("error", "Unknown error")
                await status_msg.edit_text(f"❌ Download failed: {error_msg}")

        except Exception as e:
            logger.exception("Unexpected error during Instagram download", error=str(e))
            await status_msg.edit_text(f"❌ An unexpected error occurred: `{e}`")

    def _download_instagram_post(self, url: str) -> bool:
        """Blocking Instaloader download logic to be run in a separate thread."""
        try:
            # Initialize Instaloader with custom settings
            L = instaloader.Instaloader(
                download_pictures=True,
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                dirname_pattern=str(self.downloads_path),
                filename_pattern="{date_utc}_Instagram_{shortcode}",
            )

            # Try to load existing session
            session_loaded = False
            try:
                # First try with username if available
                if hasattr(self.settings, 'instagram_username') and self.settings.instagram_username:
                    L.load_session_from_file(self.settings.instagram_username)
                    session_loaded = True
                    logger.info("Loaded Instagram session", username=self.settings.instagram_username)
                else:
                    # Try to find any available session file
                    import glob
                    session_files = glob.glob(os.path.expanduser("~/.config/instaloader/session-*"))
                    if session_files:
                        # Use the most recent session file
                        latest_session = max(session_files, key=os.path.getmtime)
                        username = os.path.basename(latest_session).replace('session-', '')
                        L.load_session_from_file(username)
                        session_loaded = True
                        logger.info("Loaded Instagram session from latest file", username=username)
            except Exception as e:
                logger.warning("Could not load Instagram session", error=str(e))
                session_loaded = False
            
            # Extract shortcode from URL
            import re
            shortcode_match = re.search(r'/p/([A-Za-z0-9_-]+)/', url)
            if not shortcode_match:
                shortcode_match = re.search(r'/reel/([A-Za-z0-9_-]+)/', url)
            
            if not shortcode_match:
                return {"success": False, "error": "Could not extract shortcode from URL", "files": []}
 

            shortcode = shortcode_match.group(1)
            logger.info("Extracted shortcode", shortcode=shortcode)
            post = instaloader.Post.from_shortcode(L.context, shortcode)

            # Get files before download for comparison
            files_before = self._get_all_files_in_directory(self.downloads_path)

            # Download the post
            L.download_post(post, target="")  # Empty string uses dirname_pattern
            
            # Get files after download
            files_after = self._get_all_files_in_directory(self.downloads_path)
            new_files = list(set(files_after) - set(files_before))

            return {"success": True, "error": None, "files": new_files}
        except Exception as e:
            logger.error("Instaloader download failed", error=str(e), url=url)
            return {"success": False, "error": str(e), "files": []}

    def _get_all_files_in_directory(self, directory: Path) -> List[Path]:
        """Get all files in directory recursively."""
        files = []
        try:
            for file_path in directory.rglob('*'):
                if file_path.is_file():
                    files.append(file_path)
        except (OSError, PermissionError) as e:
            logger.warning("Error scanning directory", directory=str(directory), error=str(e))
        return files

    async def _bot_api_worker(self):
        """Worker for Bot API uploads with file counting."""
        logger.info("Bot API worker started")
        while True:
            file_path, file_number, total_files = await self.bot_api_queue.get()
            try:
                await self._increment_active_uploads()

                caption = f"Media File ({file_number}/{total_files})"
                success = await self._send_via_bot_api(file_path, caption)

                if success:
                    await self._increment_completed()
                else:
                    await self._increment_failed()

            except Exception as e:
                logger.exception("Bot API worker error", error=str(e), filename=file_path.name)
                await self._increment_failed()
            finally:
                await self._decrement_active_uploads()
                self.bot_api_queue.task_done()

    async def _telethon_worker(self):
        """Worker for Telethon uploads with file counting."""
        logger.info("Telethon worker started")
        while True:
            file_path, file_number, total_files = await self.telethon_queue.get()
            try:
                await self._increment_active_uploads()

                caption = f"Media File ({file_number}/{total_files})"
                success = await self._send_via_telethon(file_path, caption)

                if success:
                    await self._increment_completed()
                else:
                    await self._increment_failed()

            except Exception as e:
                logger.exception("Telethon worker error", error=str(e), filename=file_path.name)
                await self._increment_failed()
            finally:
                await self._decrement_active_uploads()
                self.telethon_queue.task_done()

    @retry(
        retry=retry_if_exception_type((RetryAfter, FloodWaitError, NetworkError)),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        stop=stop_after_attempt(3)
    )
    async def process_single_file(self, file_path: Path) -> bool:
        """Process a single file with retry logic and rate limiting."""
        async with self.throttler:
            try:
                file_size = file_path.stat().st_size

                # Get file number and total count for queue consistency
                file_number = await self._get_next_file_number()
                total_files = self._total_media_count or 1
                
                logger.info("Processing file",
                            progress=f"{file_number}/{total_files}",
                            filename=file_path.name,
                            size=self._format_bytes(file_size))

                # Determine upload method
                caption = f"Media File ({file_number}/{total_files})"
                if file_size <= self.settings.large_file_threshold:
                    logger.info("Using Bot API (<= threshold)", threshold=self._format_bytes(self.settings.large_file_threshold))
                    await self.bot_api_queue.put((file_path, file_number, total_files))
                    success = True  # Queue operation success
                    method = "bot_api"
                else:
                    logger.info("Using Telethon (> threshold)", threshold=self._format_bytes(self.settings.large_file_threshold))
                    await self.telethon_queue.put((file_path, file_number, total_files))
                    success = True  # Queue operation success
                    method = "telethon"

                # Note: File deletion and logging will now be handled by the workers
                logger.info("File queued for processing", filename=file_path.name, method=method)

                # Log successful queuing
                await self.db.log_file_operation(file_path.name, file_size, f"{method}_queued", True)

                return success

            except Exception as e:
                logger.error("File processing failed",
                             filename=file_path.name, error=str(e))
                # Safely get file size for logging
                try:
                    file_size = file_path.stat().st_size
                except (FileNotFoundError, OSError):
                    file_size = 0
                    
                await self.db.log_file_operation(file_path.name, file_size, "process_error", False, str(e))
                # Don't increment counters here as this is a queue failure, not upload failure
                return False

    async def _send_via_bot_api(self, file_path: Path, caption: str) -> bool:
        """Modified Bot API send method with custom caption."""
        max_retries = self.settings.max_retry_attempts
        retry_delay = 3
        attempt = 0

        # Create a semaphore for Bot API uploads if not already defined
        if not hasattr(self, '_bot_api_upload_semaphore'):
            self._bot_api_upload_semaphore = asyncio.Semaphore(self.settings.max_concurrent_uploads)

        async with self._bot_api_upload_semaphore:
            while attempt < max_retries:
                try:
                    # Check if file still exists
                    if not file_path.exists():
                        logger.error("File no longer exists", filename=file_path.name)
                        await self.db.log_file_operation(file_path.name, 0, "bot_api", False, "File not found")
                        return False
                    
                    try:
                        file_size = file_path.stat().st_size
                        mime_type = magic.from_file(str(file_path), mime=True)
                    except (FileNotFoundError, OSError, PermissionError) as e:
                        logger.error("File access error", filename=file_path.name, error=str(e))
                        await self.db.log_file_operation(file_path.name, 0, "bot_api", False, f"File access error: {str(e)}")
                        return False
                    
                    # Check file size limits for Bot API
                    if file_size > BOT_API_MAX_FILE_SIZE:
                        error_msg = f"File too large for Bot API: {self._format_bytes(file_size)} > {self._format_bytes(BOT_API_MAX_FILE_SIZE)}"
                        logger.error("File too large for Bot API", filename=file_path.name, size=self._format_bytes(file_size))
                        await self.db.log_file_operation(file_path.name, file_size, "bot_api", False, error_msg)
                        return False
                        
                    # Check memory usage limits
                    if file_size > MAX_MEMORY_USAGE_PER_FILE:
                        error_msg = f"File too large for memory loading: {self._format_bytes(file_size)}"
                        logger.error("File too large for memory", filename=file_path.name, size=self._format_bytes(file_size))
                        await self.db.log_file_operation(file_path.name, file_size, "bot_api", False, error_msg)
                        return False

                    file_data = None

                    try:
                        async with aiofiles.open(file_path, 'rb') as file:
                            file_data = await file.read()
                    except (FileNotFoundError, PermissionError, OSError) as e:
                        logger.error("Failed to read file", filename=file_path.name, error=str(e))
                        await self.db.log_file_operation(file_path.name, file_size, "bot_api", False, f"Read error: {str(e)}")
                        return False
                    except MemoryError as e:
                        logger.error("Out of memory reading file", filename=file_path.name, size=self._format_bytes(file_size))
                        await self.db.log_file_operation(file_path.name, file_size, "bot_api", False, "Out of memory")
                        return False

                    try:
                        if mime_type.startswith('image/'):
                            await self.bot_app.bot.send_photo(
                                chat_id=self.settings.target_chat_id,
                                photo=file_data,
                                caption=caption
                            )
                        elif mime_type.startswith('video/'):
                            await self.bot_app.bot.send_video(
                                chat_id=self.settings.target_chat_id,
                                video=file_data,
                                caption=caption
                            )
                        else:
                            await self.bot_app.bot.send_document(
                                chat_id=self.settings.target_chat_id,
                                document=file_data,
                                caption=caption
                            )
                    finally:
                        # Explicitly clear file_data from memory
                        file_data = None

                    # Log successful upload
                    await self.db.log_file_operation(file_path.name, file_size, "bot_api", True)
                    
                    await asyncio.sleep(self._bot_api_pause)

                    # Delete file after successful upload
                    if file_path.exists():
                        try:
                            await asyncio.to_thread(file_path.unlink)
                            logger.info("Deleted file after successful upload", filename=file_path.name)
                        except Exception as e:
                            logger.warning("Failed to delete file after upload", filename=file_path.name, error=str(e))
                    
                    return True

                except RetryAfter as e:
                    wait_time = getattr(e, "retry_after", retry_delay)
                    logger.warning("Rate limit hit - waiting", wait_time=wait_time)
                    await self.db.log_file_operation(file_path.name, 0, "bot_api", False, f"Rate limited, attempt {attempt + 1}")
                    await asyncio.sleep(wait_time)
                    attempt += 1
                except TelegramError as e:
                    logger.error("Telegram API error", error=str(e), filename=file_path.name, attempt=attempt + 1)
                    await self.db.log_file_operation(file_path.name, 0, "bot_api", False, f"Telegram error: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    attempt += 1
                except Exception as e:
                    logger.error("Upload failed", error=str(e), filename=file_path.name, attempt=attempt + 1)
                    await self.db.log_file_operation(file_path.name, 0, "bot_api", False, f"Upload error: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    attempt += 1

            # All attempts failed
            await self.db.log_file_operation(file_path.name, 0, "bot_api", False, f"Failed after {max_retries} attempts")
            return False

    async def _send_via_telethon(self, file_path: Path, caption: str) -> bool:
        """Modified Telethon send method with custom caption."""
        max_retries = self.settings.max_retry_attempts
        attempt = 0
        retry_delay = 5

        async with self._telethon_upload_semaphore:
            while attempt < max_retries:
                try:
                     # Check if file still exists and get size
                    if not file_path.exists():
                        logger.error("File no longer exists", filename=file_path.name)
                        await self.db.log_file_operation(file_path.name, 0, "telethon", False, "File not found")
                        return False
                        
                    try:
                        file_size = file_path.stat().st_size
                    except (FileNotFoundError, OSError) as e:
                        logger.error("File access error", filename=file_path.name, error=str(e))
                        await self.db.log_file_operation(file_path.name, 0, "telethon", False, f"File access error: {str(e)}")
                        return False
                    
                    # Check file size limits for Telethon
                    if file_size > TELETHON_MAX_FILE_SIZE:
                        error_msg = f"File too large for Telethon: {self._format_bytes(file_size)} > {self._format_bytes(TELETHON_MAX_FILE_SIZE)}"
                        logger.error("File too large for Telethon", filename=file_path.name, size=self._format_bytes(file_size))
                        await self.db.log_file_operation(file_path.name, file_size, "telethon", False, error_msg)
                        return False
                    
                    # Telethon handles large files more efficiently (streams), so no memory check needed                    
                    await self.telethon_client.send_file(
                        entity=self.settings.target_chat_id,
                        file=str(file_path),
                        caption=caption
                    )

                    # Log successful upload
                    await self.db.log_file_operation(file_path.name, file_size, "telethon", True)
                    
                    await asyncio.sleep(self._telethon_pause)

                    # Delete file after successful upload
                    if file_path.exists():
                        try:
                            await asyncio.to_thread(file_path.unlink)
                            logger.info("Deleted file after successful upload", filename=file_path.name)
                        except Exception as e:
                            logger.warning("Failed to delete file after upload", filename=file_path.name, error=str(e))
                    
                    return True

                except FloodWaitError as e:
                    wait_seconds = getattr(e, "seconds", retry_delay)
                    logger.warning("Flood wait error", wait_seconds=wait_seconds, filename=file_path.name)
                    await self.db.log_file_operation(file_path.name, 0, "telethon", False, f"Flood wait {wait_seconds}s, attempt {attempt + 1}")
                    await asyncio.sleep(wait_seconds)
                    attempt += 1
                except Exception as e:
                    logger.error("Telethon upload failed", error=str(e), filename=file_path.name, attempt=attempt + 1)
                    await self.db.log_file_operation(file_path.name, 0, "telethon", False, f"Upload error: {str(e)}")
                    await asyncio.sleep(retry_delay)
                    attempt += 1

            # All attempts failed
            await self.db.log_file_operation(file_path.name, 0, "telethon", False, f"Failed after {max_retries} attempts")
            return False

    def _find_media_files(self) -> List[Path]:
        """Find all media files in downloads directory."""
        supported_extensions = self._get_supported_extensions()

        files = []
        try:
            for file_path in self.downloads_path.rglob('*'):
                try:
                    if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                        files.append(file_path)
                except (OSError, PermissionError) as e:
                    logger.warning("Error accessing file during scan", filename=str(file_path), error=str(e))
        except (OSError, PermissionError) as e:
            logger.error("Error scanning downloads directory", directory=str(self.downloads_path), error=str(e))
 

        # Sort newest first (by modification time)
        try:
            return sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
        except (OSError, PermissionError) as e:
            logger.warning("Error sorting files, returning unsorted list", error=str(e))
            return files

    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
    
    def _get_supported_extensions(self) -> set:
        """Get set of supported file extensions."""
        return {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
            '.pdf', '.doc', '.docx', '.txt', '.zip', '.rar', '.7z',
            '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'
        }

    def _find_recently_modified_files(self, directory: Path, time_threshold: int) -> List[Path]:
        """Find files modified within the last `time_threshold` seconds."""
        if not directory.exists() or not directory.is_dir():
            logger.warning("Directory does not exist or is not a directory", directory=str(directory))
            return []
            
        current_time = time.time()
        recent_files = []
        supported_extensions = self._get_supported_extensions()
        
        try:
            for file_path in directory.rglob('*'):
                try:
                    if file_path.is_file():
                        stat_info = file_path.stat()
                        if ((current_time - stat_info.st_mtime) < time_threshold and
                            file_path.suffix.lower() in supported_extensions):
                            recent_files.append(file_path)
                except (OSError, PermissionError) as e:
                    logger.warning("Error accessing file", filename=str(file_path), error=str(e))
                    continue
        except (OSError, PermissionError) as e:
            logger.error("Error scanning directory", directory=str(directory), error=str(e))
        
        try:
            return sorted(recent_files, key=lambda x: x.stat().st_mtime, reverse=True)
        except (OSError, PermissionError) as e:
            logger.warning("Error sorting recent files, returning unsorted list", error=str(e))
            return recent_files

    def _find_newly_downloaded_files(self, directory: Path, time_threshold: int = 300) -> List[Path]:
        """Find files downloaded within the last `time_threshold` seconds."""
        current_time = time.time()
        recent_files = []
        supported_extensions = self._get_supported_extensions()
        
        for file_path in directory.rglob('*'):
            try:
                if file_path.is_file():
                    stat_info = file_path.stat()
                    if ((current_time - stat_info.st_mtime) < time_threshold and
                        file_path.suffix.lower() in supported_extensions):
                        recent_files.append(file_path)
            except (OSError, PermissionError) as e:
                logger.warning("Error accessing file", filename=str(file_path), error=str(e))
                continue
        
        try:
            return sorted(recent_files, key=lambda x: x.stat().st_mtime, reverse=True)
        except (OSError, PermissionError) as e:
            logger.warning("Error sorting newly downloaded files, returning unsorted list", error=str(e))
            return recent_files

    def _start_file_watcher_if_needed(self):
        """Start file watcher if auto-watch is enabled and not already running."""
        if (self.settings.auto_watch_files and 
            self.observer and 
            not self.is_watching and 
            self.bot_app is not None):
            self.observer.start()
            self.is_watching = True
            logger.info("Auto file watcher started")

    async def shutdown(self):
        """Shutdown the bot gracefully."""
        logger.info("Shutting down enhanced Telegram bot")

        shutdown_tasks = []

        # Stop file watcher

        if self.observer and self.is_watching and self.observer.is_alive():
            try:
                self.observer.stop()
                self.observer.join(timeout=5.0)  # Add timeout to prevent hanging
                self.is_watching = False
                logger.info("File watcher stopped")
            except Exception as e:
                logger.error("Error stopping file watcher", error=str(e))

        # Shutdown Telegram clients
        if self.telethon_client:
            shutdown_tasks.append(self.telethon_client.disconnect())

        if self.bot_app:
            shutdown_tasks.append(self.bot_app.shutdown())

         # Close database
        shutdown_tasks.append(self.db.close())

        # Execute all shutdown tasks concurrently with timeout
        if shutdown_tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*shutdown_tasks, return_exceptions=True), timeout=30.0)
                logger.info("All components shut down successfully")
            except asyncio.TimeoutError:
                logger.warning("Shutdown timeout reached, some components may not have closed cleanly")
            except Exception as e:
                logger.error("Error during shutdown", error=str(e))

    async def _safe_edit_message(self, message, new_text: str, max_retries: int = 3) -> bool:
        """Safely edit a message with retry logic."""
        for attempt in range(max_retries):
            try:
                await message.edit_text(new_text)
                return True
            except RetryAfter as e:
                if attempt < max_retries - 1:  # Don't sleep on last attempt
                    await asyncio.sleep(e.retry_after)
            except TelegramError as e:
                logger.warning("Failed to edit message", error=str(e), attempt=attempt + 1)
                if attempt >= max_retries - 1:
                    return False
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        return False


async def main():
    """Initializes and runs the bot with proper async lifecycle management."""
    settings = BotSettings()
    bot = EnhancedTelegramBot(settings)
    await bot.initialize()

    # Start file watcher if needed
    bot._start_file_watcher_if_needed()

    if bot.bot_app is None:
        logger.error("Bot application failed to initialize.")
        return

    # Use a future to wait for a shutdown signal
    shutdown_event = asyncio.Future()

    try:
        
        await bot.bot_app.initialize()
        await bot.bot_app.start()
        await bot.bot_app.updater.start_polling()

        logger.info("Bot is now running. Press Ctrl+C to stop.")

        # Wait indefinitely until the shutdown_event is set
        await shutdown_event
    
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received. Starting graceful shutdown...")
    finally:
        # Stop the updater first to prevent new updates from coming in
        if bot.bot_app and bot.bot_app.updater and bot.bot_app.updater.running:
            await bot.bot_app.updater.stop()
        
        # Now, stop the main application
        if bot.bot_app and bot.bot_app.running:
            await bot.bot_app.stop()

        # Call your custom shutdown logic
        await bot.shutdown()
        logger.info("Bot has been shut down gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application terminated.")