"""Configuration management for Instagram bot."""
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path

@dataclass
class BotConfig:
    """Main bot configuration"""
    telegram: 'TelegramConfig'
    database: 'DatabaseConfig'
    instagram: 'InstagramConfig'
    upload: 'UploadConfig'
    downloads_path: Path
    uploads_path: Path
    temp_path: Path
    bot_api_limit: Optional[int] = 50 * 1024 * 1024  # 50MB
    
    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Create BotConfig from environment variables."""
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
            database_path=Path(os.getenv("DATABASE_PATH", "data/bot_data.db")),
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
            max_concurrent_uploads=int(os.getenv("MAX_CONCURRENT_UPLOADS", "3")),
            large_file_threshold=int(os.getenv("LARGE_FILE_THRESHOLD", str(20 * 1024 * 1024))),
            bot_api_max_size=int(os.getenv("BOT_API_MAX_SIZE", str(50 * 1024 * 1024))),
            telethon_max_size=int(os.getenv("TELETHON_MAX_SIZE", str(2 * 1024 * 1024 * 1024))),
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
        
        return cls(
            telegram=telegram_config,
            database=database_config,
            instagram=instagram_config,
            upload=upload_config,
            downloads_path=Path(os.getenv("DOWNLOADS_PATH", "downloads")),
            uploads_path=Path(os.getenv("UPLOADS_PATH", "uploads")),
            temp_path=Path(os.getenv("TEMP_PATH", "temp")),
            bot_api_limit=int(os.getenv("BOT_API_LIMIT", str(50 * 1024 * 1024)))
        )

# Admin user IDs are now handled in TelegramConfig

@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    path: Path
    pool_size: int = 5
    max_connections: int = 10
    timeout: int = 30
    backup_path: Optional[Path] = None
    wal_mode: bool = True

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
    admin_user_ids: List[int] = field(default_factory=list)

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
    downloads_path: Path = Path("downloads")
    uploads_path: Path = Path("uploads")
    temp_path: Path = Path("temp")

@dataclass
@dataclass
class InstagramConfig:
    """Instagram-specific configuration settings"""
    username: Optional[str] = None
    cookies_file: Optional[Path] = None
    downloads_path: Path = Path("downloads/instagram")
    download_timeout: int = 300
    retry_delay: int = 60
    max_retries: int = 3
    caption_max_length: int = 200
    session_expiry: int = 86400  # 24 hours in seconds

@dataclass
class BotConfig:
    """Main bot configuration"""
    database: DatabaseConfig
    telegram: TelegramConfig
    upload: UploadConfig
    instagram: InstagramConfig
    downloads_path: Path = Path("downloads")
    uploads_path: Path = Path("uploads")
    temp_path: Path = Path("temp")
    logs_path: Path = Path("logs")
    config_path: Path = Path("config")

    @classmethod
    def from_env(cls, env: Dict[str, Any] = None) -> 'BotConfig':
        """Create configuration from environment variables."""
        if env is None:
            env = os.environ
        
        database = DatabaseConfig(
            path=Path(env.get('DATABASE_PATH', 'data/bot_data.db')),
            pool_size=int(env.get('DATABASE_POOL_SIZE', '5'))
        )
        
        telegram = TelegramConfig(
            bot_token=env['BOT_TOKEN'],
            api_id=int(env['API_ID']),
            api_hash=env['API_HASH'],
            target_chat_id=int(env.get('TARGET_CHAT_ID', '0')),
            admin_user_ids=[int(id.strip()) 
                          for id in env.get('ADMIN_USER_IDS', '').split(',') 
                          if id.strip()]
        )
        
        upload = UploadConfig(
            downloads_path=Path(env.get('DOWNLOADS_PATH', 'downloads')),
            uploads_path=Path(env.get('UPLOADS_PATH', 'uploads')),
            temp_path=Path(env.get('TEMP_PATH', 'temp'))
        )
        
        instagram = InstagramConfig(
            username=env.get('INSTAGRAM_USERNAME'),
            cookies_file=(Path(env['COOKIES_FILE']) 
                        if 'COOKIES_FILE' in env else None),
            downloads_path=Path(env.get('INSTAGRAM_DOWNLOADS_PATH', 
                                      'downloads/instagram'))
        )
        
        return cls(
            database=database,
            telegram=telegram,
            upload=upload,
            instagram=instagram,
            downloads_path=Path(env.get('DOWNLOADS_PATH', 'downloads')),
            uploads_path=Path(env.get('UPLOADS_PATH', 'uploads')),
            temp_path=Path(env.get('TEMP_PATH', 'temp')),
            logs_path=Path(env.get('LOGS_PATH', 'logs')),
            config_path=Path(env.get('CONFIG_PATH', 'config'))
        )
    download_progress_enabled: bool = True
    cookies_auto_refresh: bool = True
    supported_extensions: set = field(default_factory=lambda: {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff',
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm',
        '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'
    })

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
