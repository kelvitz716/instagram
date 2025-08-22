from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

@dataclass
class TelegramConfig:
    """Telegram-specific configuration settings"""
    bot_token: str
    api_id: int
    api_hash: str
    target_chat_id: int
    phone_number: Optional[str] = None
    session_name: str = "telegram_bot_session"
    connection_timeout: int = 30
    read_timeout: int = 30
    bot_api_timeout: int = 60
    telethon_timeout: int = 300
    flood_control_base_delay: float = 1.0
    message_edit_retry_delay: float = 2.0
    network_retry_attempts: int = 5

@dataclass
class UploadConfig:
    """Upload operation configuration settings"""
    max_concurrent_uploads: int = 3
    bot_api_max_size: int = 50 * 1024 * 1024  # 50MB
    telethon_max_size: int = 2 * 1024 * 1024 * 1024  # 2GB
    large_file_threshold: int = 20 * 1024 * 1024  # 20MB
    bot_api_pause_seconds: float = 1.0
    telethon_pause_seconds: float = 0.5
    max_messages_per_minute: int = 20
    batch_size: int = 10
    progress_update_threshold: float = 5.0  # Percentage
    status_update_interval: float = 5.0  # Seconds

@dataclass
class InstagramConfig:
    """Instagram-specific configuration settings"""
    username: Optional[str] = None
    firefox_cookies_path: Optional[str] = None
    download_timeout: int = 300
    retry_delay: int = 60
    max_retries: int = 3
    caption_max_length: int = 200
    download_progress_enabled: bool = True
    cookies_auto_refresh: bool = True
    supported_extensions: set = field(default_factory=lambda: {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'
    })

@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    db_path: str = "bot_data.db"
    pool_size: int = 5
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0

@dataclass
class FileWatcherConfig:
    """File watcher configuration settings"""
    enabled: bool = False
    recursive: bool = True
    poll_interval: float = 1.0
    stable_delay: int = 30  # Time to wait for file to be stable
    max_batch_size: int = 100

@dataclass
class LoggingConfig:
    """Logging configuration settings"""
    level: str = "INFO"
    file: Optional[str] = None
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    max_file_size: int = 10 * 1024 * 1024  # 10MB
    backup_count: int = 5

@dataclass
class BotConfig:
    """Main bot configuration container"""
    telegram: TelegramConfig
    upload: UploadConfig = field(default_factory=UploadConfig)
    instagram: InstagramConfig = field(default_factory=InstagramConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    file_watcher: FileWatcherConfig = field(default_factory=FileWatcherConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    downloads_path: Path = Path("downloads")
    uploads_path: Path = Path("uploads")
    temp_path: Path = Path("temp")
    version: str = "2.0.0"

    def __post_init__(self):
        """Ensure all paths exist after initialization"""
        for path in [self.downloads_path, self.uploads_path, self.temp_path]:
            path.mkdir(parents=True, exist_ok=True)
