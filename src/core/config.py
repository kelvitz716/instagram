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
    session_name: str = "telegram_bot_session"
    connection_timeout: int = 30
    read_timeout: int = 30
    bot_api_timeout: int = 60
    telethon_timeout: int = 300

@dataclass
class UploadConfig:
    """Upload operation configuration settings"""
    max_concurrent_uploads: int = 3
    bot_api_max_size: int = 50 * 1024 * 1024  # 50MB
    telethon_max_size: int = 2 * 1024 * 1024 * 1024  # 2GB
    large_file_threshold: int = 20 * 1024 * 1024  # 20MB
    bot_api_pause_seconds: float = 1.0
    telethon_pause_seconds: float = 0.5

@dataclass
class InstagramConfig:
    """Instagram-specific configuration settings"""
    username: Optional[str] = None
    firefox_cookies_path: Optional[str] = None
    download_timeout: int = 300
    retry_delay: int = 60
    max_retries: int = 3

@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    db_path: str = "bot_data.db"
    pool_size: int = 5
    timeout: int = 30

@dataclass
class BotConfig:
    """Main bot configuration container"""
    telegram: TelegramConfig
    upload: UploadConfig = field(default_factory=UploadConfig)
    instagram: InstagramConfig = field(default_factory=InstagramConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    downloads_path: Path = Path("downloads")
    log_level: str = "INFO"
    auto_watch_files: bool = False
