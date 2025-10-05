#!/usr/bin/env python3
"""
Instagram Telegram Bot - Main Entry Point

This is the main entry point for the Instagram Telegram Bot.
It handles configuration loading, logging setup, and bot initialization.
"""
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import NoReturn, Optional

# Add the parent directory to sys.path to make 'src' importable
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

import structlog
from src.bot import EnhancedTelegramBot, run_bot
from src.core.config import BotConfig
from src.core.monitoring.logging import setup_structured_logging
from src.core.validate_env import validate_environment

logger = structlog.get_logger(__name__)

def setup_signal_handlers() -> None:
    """Set up signal handlers for graceful shutdown."""
    def handler(signum: int, frame) -> NoReturn:
        logger.info("Received termination signal", signal=signum)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

def load_environment() -> None:
    """Load and validate environment variables."""
    # Load .env file if it exists
    env_path = Path(".env")
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    
    # Validate required environment variables
    missing = validate_environment()
    if missing:
        logger.error("Missing required environment variables", missing=missing)
        sys.exit(1)

def setup_directories(config: BotConfig) -> None:
    """Create required directories with proper permissions."""
    directories = [
        config.downloads_path,
        config.uploads_path,
        config.temp_path,
        Path('logs'),  # Direct path for logs
        Path('config'),  # Direct path for config
        config.database.path.parent,
        config.instagram.downloads_path
    ]
    
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            logger.info("Created directory", path=str(directory))
        except Exception as e:
            logger.error("Failed to create directory", path=str(directory), error=str(e))
            sys.exit(1)

async def initialize_bot(config: BotConfig) -> Optional[EnhancedTelegramBot]:
    """Initialize the bot with configuration."""
    try:
        bot = EnhancedTelegramBot(config)
        await bot.initialize()
        return bot
    except Exception as e:
        logger.exception("Failed to initialize bot", error=str(e))
        return None

async def main() -> int:
    """Main entry point for the bot."""
    try:
        # Load environment variables
        load_environment()

        # Load configuration
        from src.core.load_config import load_configuration
        config = load_configuration()

        # Set up logging
        setup_structured_logging(config.logging)

        # Create required directories
        setup_directories(config)

        # Initialize the bot
        bot = await initialize_bot(config)
        if bot is None:
            logger.error("Bot initialization failed")
            return 1
            
        # Run the bot
        await run_bot(bot)
        return 0
        
    except Exception as e:
        logger.exception("Fatal error in main loop", error=str(e))
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))