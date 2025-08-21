"""Configuration loading utilities."""
import os
from pathlib import Path
from dotenv import load_dotenv
from src.core.config import BotConfig, TelegramConfig, UploadConfig, InstagramConfig, DatabaseConfig

def load_configuration() -> BotConfig:
    """Load configuration from environment variables."""
    # Load .env file if it exists
    load_dotenv()
    
    telegram_config = TelegramConfig(
        bot_token=os.getenv('BOT_TOKEN', ''),
        api_id=int(os.getenv('API_ID', '0')),
        api_hash=os.getenv('API_HASH', ''),
        target_chat_id=int(os.getenv('TARGET_CHAT_ID', '0')),
        session_name=os.getenv('SESSION_NAME', 'telegram_bot_session')
    )
    
    instagram_config = InstagramConfig(
        username=os.getenv('INSTAGRAM_USERNAME'),
        firefox_cookies_path=os.getenv('FIREFOX_COOKIES_PATH')
    )
    
    database_config = DatabaseConfig(
        db_path=os.getenv('DATABASE_PATH', 'bot_data.db')
    )
    
    upload_config = UploadConfig()
    
    return BotConfig(
        telegram=telegram_config,
        instagram=instagram_config,
        database=database_config,
        upload=upload_config,
        downloads_path=Path(os.getenv('DOWNLOADS_PATH', 'downloads')),
        log_level=os.getenv('LOG_LEVEL', 'INFO'),
        auto_watch_files=os.getenv('AUTO_WATCH_FILES', 'false').lower() == 'true'
    )
