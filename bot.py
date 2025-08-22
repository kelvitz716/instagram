#!/usr/bin/env python3
"""
Instagram Telegram Bot - Main Entry Point
"""
import asyncio
import logging
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