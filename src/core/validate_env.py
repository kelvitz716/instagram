"""Environment validation for the Instagram bot."""
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def validate_environment():
    """Validate and log environment configuration."""
    required_vars = {
        'BOT_TOKEN': 'Telegram bot token',
        'API_ID': 'Telegram API ID',
        'API_HASH': 'Telegram API hash',
        'TARGET_CHAT_ID': 'Target chat ID for uploads'
    }
    
    missing = []
    for var, desc in required_vars.items():
        if not os.getenv(var):
            missing.append(f"{desc} ({var})")
    
    if missing:
        raise ValueError(
            "Missing required environment variables:\n" +
            "\n".join(f"- {item}" for item in missing)
        )
    
    # Validate paths
    downloads_path = Path(os.getenv('DOWNLOADS_PATH', 'downloads'))
    downloads_path.mkdir(parents=True, exist_ok=True)
    
    # Log configuration
    logger.info("Environment configuration:")
    logger.info(f"- Downloads path: {downloads_path}")
    logger.info(f"- Database path: {os.getenv('DATABASE_PATH', 'bot_data.db')}")
    if os.getenv('INSTAGRAM_USERNAME'):
        logger.info(f"- Instagram username: {os.getenv('INSTAGRAM_USERNAME')}")
    
    return True