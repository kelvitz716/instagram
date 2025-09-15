"""Configuration loading utilities."""
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from src.core.config import (
    BotConfig, TelegramConfig, UploadConfig, InstagramConfig, 
    DatabaseConfig, FileWatcherConfig, LoggingConfig
)

def get_env_int(key: str, default: int = 0) -> int:
    """Get integer value from environment variable."""
    try:
        return int(os.getenv(key, default))
    except (ValueError, TypeError):
        return default

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
    
    # Telegram Configuration
    telegram_config = TelegramConfig(
        bot_token=os.getenv('BOT_TOKEN', ''),
        api_id=get_env_int('API_ID'),
        api_hash=os.getenv('API_HASH', ''),
        target_chat_id=get_env_int('TARGET_CHAT_ID'),
        phone_number=os.getenv('PHONE_NUMBER'),
        session_name=os.getenv('SESSION_NAME', 'telegram_bot_session'),
        connection_timeout=get_env_int('CONNECTION_TIMEOUT', 30),
        read_timeout=get_env_int('READ_TIMEOUT', 30),
        bot_api_timeout=get_env_int('BOT_API_TIMEOUT', 60),
        telethon_timeout=get_env_int('TELETHON_TIMEOUT', 300),
        flood_control_base_delay=get_env_float('FLOOD_CONTROL_BASE_DELAY', 1.0),
        message_edit_retry_delay=get_env_float('MESSAGE_EDIT_RETRY_DELAY', 2.0),
        network_retry_attempts=get_env_int('NETWORK_RETRY_ATTEMPTS', 5)
    )
    
    # Upload Configuration
    upload_config = UploadConfig(
        max_concurrent_uploads=get_env_int('MAX_CONCURRENT_UPLOADS', 3),
        large_file_threshold=get_env_int('LARGE_FILE_THRESHOLD', 20 * 1024 * 1024),
        bot_api_pause_seconds=get_env_float('BOT_API_PAUSE_SECONDS', 1.0),
        telethon_pause_seconds=get_env_float('TELETHON_PAUSE_SECONDS', 0.5),
        max_messages_per_minute=get_env_int('MAX_MESSAGES_PER_MINUTE', 20),
        batch_size=get_env_int('BATCH_SIZE', 10),
        progress_update_threshold=get_env_float('PROGRESS_UPDATE_THRESHOLD', 5.0),
        status_update_interval=get_env_float('STATUS_UPDATE_INTERVAL', 5.0)
    )
    
    # Instagram Configuration
    instagram_config = InstagramConfig(
        username=os.getenv('INSTAGRAM_USERNAME'),
        firefox_cookies_path=os.getenv('FIREFOX_COOKIES_PATH'),
        download_timeout=get_env_int('INSTAGRAM_DOWNLOAD_TIMEOUT', 300),
        retry_delay=get_env_int('INSTAGRAM_RETRY_DELAY', 60),
        max_retries=get_env_int('INSTAGRAM_MAX_RETRIES', 3),
        caption_max_length=get_env_int('INSTAGRAM_CAPTION_MAX_LENGTH', 200),
        download_progress_enabled=get_env_bool('INSTAGRAM_DOWNLOAD_PROGRESS', True),
        cookies_auto_refresh=get_env_bool('INSTAGRAM_COOKIES_AUTO_REFRESH', True)
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
        downloads_path=get_env_path('DOWNLOADS_PATH', 'downloads'),
        uploads_path=get_env_path('UPLOADS_PATH', 'uploads'),
        temp_path=get_env_path('TEMP_PATH', 'temp'),
        version=os.getenv('BOT_VERSION', '2.0.0')
    )
