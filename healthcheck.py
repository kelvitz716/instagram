#!/usr/bin/env python3
import os
import sys
import requests
from dotenv import load_dotenv

def check_bot_health():
    # Load environment variables
    load_dotenv()
    
    # Get bot token from environment
    bot_token = os.getenv('BOT_TOKEN')
    if not bot_token:
        print("BOT_TOKEN not found in environment variables")
        sys.exit(1)
    
    try:
        # Try to get bot information from Telegram
        response = requests.get(
            f'https://api.telegram.org/bot{bot_token}/getMe',
            timeout=5
        )
        response.raise_for_status()
        
        # Check if response contains bot information
        data = response.json()
        if not data.get('ok'):
            print("Failed to get bot information")
            sys.exit(1)
            
        print("Bot is healthy")
        sys.exit(0)
        
    except requests.RequestException as e:
        print(f"Health check failed: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    check_bot_health()