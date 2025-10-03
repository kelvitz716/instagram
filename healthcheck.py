#!/usr/bin/env python3
import os
import sys
import requests
from dotenv import load_dotenv

def check_disk_space():
    """Check available disk space."""
    import psutil
    
    try:
        # Check disk space in downloads directory
        downloads_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
        disk_usage = psutil.disk_usage(downloads_path)
        
        # Critical if disk usage is over 95%
        if disk_usage.percent >= 95:
            print(f"Critical: Disk usage at {disk_usage.percent}%")
            return False
            
        # Warning if disk usage is over 85%
        if disk_usage.percent >= 85:
            print(f"Warning: Disk usage at {disk_usage.percent}%")
            
        return True
        
    except Exception as e:
        print(f"Error checking disk space: {e}")
        return False

def check_memory_usage():
    """Check system memory usage."""
    import psutil
    
    try:
        memory = psutil.virtual_memory()
        
        # Critical if memory usage is over 90%
        if memory.percent >= 90:
            print(f"Critical: Memory usage at {memory.percent}%")
            return False
            
        # Warning if memory usage is over 80%
        if memory.percent >= 80:
            print(f"Warning: Memory usage at {memory.percent}%")
            
        return True
        
    except Exception as e:
        print(f"Error checking memory: {e}")
        return False

def check_bot_health():
    """Run comprehensive health checks."""
    # Load environment variables
    load_dotenv()
    
    healthy = True
    
    # Check disk space
    if not check_disk_space():
        healthy = False
    
    # Check memory usage
    if not check_memory_usage():
        healthy = False
    
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
            healthy = False
            
        # Check database access
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/bot_data.db')
        if not os.path.exists(db_path):
            print("Database file not found")
            healthy = False
            
        if healthy:
            print("Bot is healthy")
            sys.exit(0)
        else:
            print("Bot health check failed")
            sys.exit(1)
            
    except requests.RequestException as e:
        print(f"Health check failed: {str(e)}")
        sys.exit(1)

if __name__ == '__main__':
    check_bot_health()