#!/usr/bin/env python3
"""
Instagram Telegram Bot - Main Entry Point
"""
import asyncio
import logging
import sys
import signal
from pathlib import Path
from typing import NoReturn

# Add the parent directory to sys.path to make 'src' importable
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.bot import run_bot
from src.core.monitoring import setup_structured_logging

logger = logging.getLogger(__name__)

def signal_handler(signum: int, frame) -> NoReturn:
    """Handle termination signals gracefully."""
    logger.info("Received termination signal", signal=signum)
    sys.exit(0)

def main() -> int:
    """Main entry point with improved error handling."""
    try:
        # Set up structured logging
        setup_structured_logging()
        
        # Set up signal handlers
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        
        # Run the bot with proper setup
        run_bot()
        return 0
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        return 0
        
    except Exception as e:
        logger.exception("Fatal error in main loop", error=str(e))
        return 1

if __name__ == "__main__":
    sys.exit(main())