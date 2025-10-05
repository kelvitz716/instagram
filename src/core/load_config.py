"""Configuration loading utilities."""
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from .config import (
    BotConfig, TelegramConfig, UploadConfig, InstagramConfig, 
    DatabaseConfig
)
from ..utils.size_parser import parse_size

def get_env_int(key: str, default: int = 0) -> int:
    """Get integer value from environment variable."""
    value = os.getenv(key)
    if not value:
        return default
    
    # Try parsing as a size string first
    size = parse_size(value)
    if size is not None:
        return size
        
    # Fall back to regular integer parsing
    return int(value)

def get_env_float(key: str, default: float = 0.0) -> float:
    """Get float value from environment variable."""
    try:
        return float(os.getenv(key, default))
    except (ValueError, TypeError):
        return default

def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean value from environment variable."""
    value = os.getenv(key, str(default)).lower()
    return value in ('true', '1', 'yes', 'on', 't')

def get_env_path(key: str, default: str) -> Path:
    """Get Path value from environment variable."""
    return Path(os.getenv(key, default))

def load_configuration() -> BotConfig:
    """Load configuration from environment variables."""
    # Load .env file if it exists
    load_dotenv()
    
    # Get admin user IDs from env
    admin_user_ids = [int(id) for id in os.getenv("ADMIN_USER_IDS", "").split(",") if id]
    
    telegram_config = TelegramConfig(
        bot_token=os.getenv("BOT_TOKEN"),
        api_id=int(os.getenv("API_ID", 0)),
        api_hash=os.getenv("API_HASH"),
        target_chat_id=int(os.getenv("TARGET_CHAT_ID", 0)),
        phone_number=os.getenv("PHONE_NUMBER"),
        session_name=os.getenv("SESSION_NAME", "telegram_bot_session"),
        admin_user_ids=admin_user_ids,
        connection_timeout=int(os.getenv("CONNECTION_TIMEOUT", "30")),
        read_timeout=int(os.getenv("READ_TIMEOUT", "30")),
        bot_api_timeout=int(os.getenv("BOT_API_TIMEOUT", "60")),
        telethon_timeout=int(os.getenv("TELETHON_TIMEOUT", "300")),
        flood_control_base_delay=float(os.getenv("FLOOD_CONTROL_BASE_DELAY", "1.0")),
        message_edit_retry_delay=float(os.getenv("MESSAGE_EDIT_RETRY_DELAY", "2.0")),
        network_retry_attempts=int(os.getenv("NETWORK_RETRY_ATTEMPTS", "5"))
    )
    
    database_config = DatabaseConfig(
        path=Path(os.getenv("DATABASE_PATH", "data/bot_data.db")),
        pool_size=int(os.getenv("DATABASE_POOL_SIZE", "5")),
        max_connections=int(os.getenv("DATABASE_MAX_CONNECTIONS", "10")),
        timeout=int(os.getenv("DATABASE_TIMEOUT", "30")),
        backup_path=Path(os.getenv("DATABASE_BACKUP_PATH")) if os.getenv("DATABASE_BACKUP_PATH") else None,
        wal_mode=os.getenv("DATABASE_WAL_MODE", "true").lower() == "true"
    )
    
    instagram_config = InstagramConfig(
        username=os.getenv("INSTAGRAM_USERNAME"),
        cookies_file=Path(os.getenv("INSTAGRAM_COOKIES_FILE", "gallery-dl-cookies.txt"))
    )
    
    upload_config = UploadConfig(
        max_concurrent_uploads=get_env_int("MAX_CONCURRENT_UPLOADS", 3),
        large_file_threshold=parse_size(os.getenv("LARGE_FILE_THRESHOLD")) or (20 * 1024 * 1024),
        bot_api_max_size=parse_size(os.getenv("BOT_API_MAX_SIZE")) or (50 * 1024 * 1024),
        telethon_max_size=parse_size(os.getenv("TELETHON_MAX_SIZE")) or (2 * 1024 * 1024 * 1024),
        bot_api_pause_seconds=float(os.getenv("BOT_API_PAUSE_SECONDS", "1.0")),
        telethon_pause_seconds=float(os.getenv("TELETHON_PAUSE_SECONDS", "0.5")),
        max_messages_per_minute=int(os.getenv("MAX_MESSAGES_PER_MINUTE", "20")),
        batch_size=int(os.getenv("BATCH_SIZE", "10")),
        progress_update_threshold=float(os.getenv("PROGRESS_UPDATE_THRESHOLD", "5.0")),
        status_update_interval=float(os.getenv("STATUS_UPDATE_INTERVAL", "5.0")),
        downloads_path=Path(os.getenv("DOWNLOADS_PATH", "downloads")),
        uploads_path=Path(os.getenv("UPLOADS_PATH", "uploads")),
        temp_path=Path(os.getenv("TEMP_PATH", "temp"))
    )
    
    return BotConfig(
        telegram=telegram_config,
        database=database_config,
        instagram=instagram_config,
        upload=upload_config,
        downloads_path=Path(os.getenv("DOWNLOADS_PATH", "downloads")),
        uploads_path=Path(os.getenv("UPLOADS_PATH", "uploads")),
        temp_path=Path(os.getenv("TEMP_PATH", "temp"))
    )
    instagram_config = InstagramConfig(
        username=os.getenv('INSTAGRAM_USERNAME'),
        cookies_file=Path(os.getenv('COOKIES_FILE', 'gallery-dl-cookies.txt')),
        downloads_path=Path(os.getenv('INSTAGRAM_DOWNLOADS_PATH', 'downloads/instagram')),
        download_timeout=get_env_int('INSTAGRAM_DOWNLOAD_TIMEOUT', 300),
        retry_delay=get_env_int('INSTAGRAM_RETRY_DELAY', 60),
        max_retries=get_env_int('INSTAGRAM_MAX_RETRIES', 3),
        caption_max_length=get_env_int('INSTAGRAM_CAPTION_MAX_LENGTH', 200),
        session_expiry=get_env_int('INSTAGRAM_SESSION_EXPIRY', 86400)
    )
    
    # Database Configuration
    database_config = DatabaseConfig(
        db_path=os.getenv('DATABASE_PATH', 'bot_data.db'),
        pool_size=get_env_int('DATABASE_POOL_SIZE', 5),
        timeout=get_env_int('DATABASE_TIMEOUT', 30),
        max_retries=get_env_int('DATABASE_MAX_RETRIES', 3),
        retry_delay=get_env_float('DATABASE_RETRY_DELAY', 1.0)
    )
    
    # File Watcher Configuration
    file_watcher_config = FileWatcherConfig(
        enabled=get_env_bool('FILE_WATCHER_ENABLED', False),
        recursive=get_env_bool('FILE_WATCHER_RECURSIVE', True),
        poll_interval=get_env_float('FILE_WATCHER_POLL_INTERVAL', 1.0),
        stable_delay=get_env_int('FILE_WATCHER_STABLE_DELAY', 30),
        max_batch_size=get_env_int('FILE_WATCHER_MAX_BATCH_SIZE', 100)
    )
    
    # Logging Configuration
    logging_config = LoggingConfig(
        level=os.getenv('LOG_LEVEL', 'INFO'),
        file=os.getenv('LOG_FILE'),
        format=os.getenv(
            'LOG_FORMAT', 
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ),
        date_format=os.getenv('LOG_DATE_FORMAT', '%Y-%m-%d %H:%M:%S'),
        max_file_size=get_env_int('LOG_MAX_FILE_SIZE', 10 * 1024 * 1024),
        backup_count=get_env_int('LOG_BACKUP_COUNT', 5)
    )
    
    # Main Bot Configuration
    return BotConfig(
        telegram=telegram_config,
        upload=upload_config,
        instagram=instagram_config,
        database=database_config,
        file_watcher=file_watcher_config,
        logging=logging_config,
        downloads_path=get_env_path('DOWNLOADS_PATH', str(Path.home() / 'downloads')),
        uploads_path=get_env_path('UPLOADS_PATH', str(Path.home() / 'uploads')),
        temp_path=get_env_path('TEMP_PATH', str(Path.home() / 'temp')),
        version=os.getenv('BOT_VERSION', '2.0.0')
    )
