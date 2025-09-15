#!/usr/bin/env python3
"""
Instagram Telegram Bot - Main Entry Point
"""
import asyncio
import logging
import sys
from pathlib import Path

# Add the parent directory to sys.path to make 'src' importable
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from src.bot import run_bot

if __name__ == "__main__":
    try:
        # Run the bot with proper setup
        run_bot()
    except KeyboardInterrupt:
        print("\nBot stopped by user")
        exit(0)
    except Exception as e:
        print(f"Error: {e}")
        exit(1)