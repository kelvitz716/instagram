#!/usr/bin/env python3
"""
Enhanced Telegram Bot with third-party libraries for better efficiency and maintainability.
"""

import asyncio
import sys
import os
import logging
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

    async def log_file_operation(self, filename: str, file_size: int, method: str,
                                 success: bool, error_msg: Optional[str] = None):
        """Log a file operation to database."""
        async with self._conn_lock:
            await self._conn.execute('''
                INSERT INTO file_stats (filename, file_size, upload_method, success, error_message)
                VALUES (?, ?, ?, ?, ?)
            ''', (filename, file_size, method, success, error_msg))
            await self._conn.commit()

    async def get_statistics(self) -> dict:
        """Get bot statistics from database."""
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

    async def close(self):
        """Close DB connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None


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
        self._single_file_counter_lock = asyncio.Lock()  # Reinitialize the lock with proper event loop
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

        # Reset counters
        self._completed_count = 0
        self._failed_count = 0
        current_batch = 1
        total_batches = (total_files + self._batch_size - 1) // self._batch_size

        for i in range(0, total_files, self._batch_size):
            batch = files[i:i + self._batch_size]
            batch_size = len(batch)

            await status_msg.edit_text(
                f"📤 Processing Batch {current_batch}/{total_batches}\n"
                f"• Total files: {total_files}\n"
                f"• Current batch: {batch_size} files\n"
                f"• Completed: {self._completed_count}/{total_files}\n"
                f"• Active uploads: {self._active_uploads}"
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
                    self._failed_count += 1

            # Wait for current batch to complete
            while (not self.bot_api_queue.empty() or
                not self.telethon_queue.empty() or
                self._active_uploads > 0):
                await asyncio.sleep(1)

            current_batch += 1

        # Final summary
        success_rate = (self._completed_count / total_files) * 100
        final_message = (
            f"✅ Upload Complete!\n\n"
            f"📊 Summary:\n"
            f"• Total files processed: {total_files}\n"
            f"• Successfully sent: {self._completed_count}\n"
            f"• Failed: {self._failed_count}\n"
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
        if not context.args or not context.args[0].startswith("https://www.instagram.com/"):
            await update.message.reply_text("Usage: /downloadig <instagram_url>")
            return

        url = context.args[0]
        status_msg = await update.message.reply_text(f"⏳ Starting download for: `{url}`")
        logger.info("Received Instagram download request", url=url)

        try:
            # Run the blocking Instaloader download function in a separate thread
            success = await asyncio.to_thread(self._download_instagram_post, url)

            if success:
                logger.info("Instagram download successful. Now processing...")
                await status_msg.edit_text("✅ Download successful! The bot is now uploading the file.")

                # Find the newly downloaded files and add them to the queue
                newly_downloaded_files = self._find_recently_modified_files(self.downloads_path, time_threshold=300)
                if newly_downloaded_files:
                    for file_path in newly_downloaded_files:
                        await self.process_single_file(file_path)
                else:
                    logger.warning("Downloaded file not found after download completion.")
                    await status_msg.edit_text("❌ Downloaded file not found. Check logs.")
            else:
                await status_msg.edit_text("❌ Download failed. Check bot logs for details.")

        except Exception as e:
            logger.exception("Unexpected error during Instagram download", error=str(e))
            await status_msg.edit_text(f"❌ An unexpected error occurred: `{e}`")

    def _download_instagram_post(self, url: str) -> bool:
        """Blocking Instaloader download logic to be run in a separate thread."""
        session_name = "instaloader_session"
        L = instaloader.Instaloader()

        try:
            with contextlib.suppress(Exception):
                L.load_session_from_file(self.settings.session_name, session_name)

            shortcode = url.strip().split("/")[-2]
            post = instaloader.Post.from_shortcode(L.context, shortcode)

            L.download_post(
                post,
                target=self.downloads_path
            )

            return True
        except Exception as e:
            logger.error("Instaloader download failed", error=str(e), url=url)
            return False

    async def _bot_api_worker(self):
        """Worker for Bot API uploads with file counting."""
        logger.info("Bot API worker started")
        while True:
            file_path, file_number, total_files = await self.bot_api_queue.get()
            try:
                self._active_uploads += 1

                caption = f"Media File ({file_number}/{total_files})"
                success = await self._send_via_bot_api(file_path, caption)

                if success:
                    self._completed_count += 1
                else:
                    self._failed_count += 1

            except Exception as e:
                logger.exception("Bot API worker error", error=str(e), filename=file_path.name)
                self._failed_count += 1
            finally:
                self._active_uploads -= 1
                self.bot_api_queue.task_done()

    async def _telethon_worker(self):
        """Worker for Telethon uploads with file counting."""
        logger.info("Telethon worker started")
        while True:
            file_path, file_number, total_files = await self.telethon_queue.get()
            try:
                self._active_uploads += 1

                caption = f"Media File ({file_number}/{total_files})"
                success = await self._send_via_telethon(file_path, caption)

                if success:
                    self._completed_count += 1
                else:
                    self._failed_count += 1

            except Exception as e:
                logger.exception("Telethon worker error", error=str(e), filename=file_path.name)
                self._failed_count += 1
            finally:
                self._active_uploads -= 1
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

                return success

            except Exception as e:
                logger.error("File processing failed",
                             filename=file_path.name, error=str(e))
                await self.db.log_file_operation(
                    file_path.name, 0, "unknown", False, str(e)
                )
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
                    # File will be deleted by worker after successful upload
                    mime_type = magic.from_file(str(file_path), mime=True)

                    async with aiofiles.open(file_path, 'rb') as file:
                        file_data = await file.read()

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
                    await asyncio.sleep(wait_time)
                    attempt += 1
                except Exception as e:
                    logger.error("Upload failed", error=str(e))
                    await asyncio.sleep(retry_delay)
                    attempt += 1

            return False

    async def _send_via_telethon(self, file_path: Path, caption: str) -> bool:
        """Modified Telethon send method with custom caption."""
        max_retries = self.settings.max_retry_attempts
        attempt = 0
        retry_delay = 5

        async with self._telethon_upload_semaphore:
            while attempt < max_retries:
                try:
                    # File will be deleted by worker after successful upload
                    await self.telethon_client.send_file(
                        entity=self.settings.target_chat_id,
                        file=str(file_path),
                        caption=caption
                    )
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
                    await asyncio.sleep(wait_seconds)
                    attempt += 1
                except Exception as e:
                    logger.error("Telethon upload failed", error=str(e))
                    await asyncio.sleep(retry_delay)
                    attempt += 1

            return False

    def _find_media_files(self) -> List[Path]:
        """Find all media files in downloads directory."""
        supported_extensions = {
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
            '.pdf', '.doc', '.docx', '.txt', '.zip', '.rar', '.7z',
            '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'
        }

        files = []
        for file_path in self.downloads_path.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                files.append(file_path)

        # Sort newest first (by modification time)
        return sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)

    @staticmethod
    def _format_bytes(size: int) -> str:
        """Format bytes in human-readable format."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _find_recently_modified_files(self, directory: Path, time_threshold: int) -> List[Path]:
        """Find files modified within the last `time_threshold` seconds."""
        current_time = time.time()
        recent_files = [f for f in directory.iterdir()
                        if f.is_file() and (current_time - f.stat().st_mtime) < time_threshold]
        return recent_files

    def _find_newly_downloaded_files(self, directory: Path) -> List[Path]:
        """Async setup only, no run_polling here."""
        if self.bot_app is None:
            raise RuntimeError("Bot application is not initialized")

        # Start file watcher if auto enabled
        if self.settings.auto_watch_files and self.observer and not self.is_watching:
            self.observer.start()
            self.is_watching = True
            logger.info("Auto file watcher started")

    async def shutdown(self):
        """Shutdown the bot gracefully."""
        logger.info("Shutting down enhanced Telegram bot")

        if self.observer and self.is_watching and self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
            self.is_watching = False

        if self.telethon_client:
            await self.telethon_client.disconnect()

        if self.bot_app:
            await self.bot_app.shutdown()

        await self.db.close()

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

    if bot.bot_app is None:
        logger.error("Bot application failed to initialize.")
        return

    # Use a future to wait for a shutdown signal
    shutdown_event = asyncio.Future()

    try:
        if bot.settings.auto_watch_files and bot.observer and not bot.is_watching:
            bot.observer.start()
            bot.is_watching = True
            logger.info("Auto file watcher started")

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