"""Core rate limiting and backoff implementation."""
import time
import random
import logging
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import json

logger = logging.getLogger(__name__)

class RateLimitConfig:
    """Configuration loader for rate limiting settings."""
    
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.load_config()
        
    def _convert_value(self, value: str) -> Any:
        """Convert string value to appropriate type."""
        value = value.strip()
        # Try boolean
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        # Try integer
        try:
            if '.' not in value:
                return int(value)
        except ValueError:
            pass
        # Try float
        try:
            return float(value)
        except ValueError:
            pass
        # Return as string
        return value

    def load_config(self):
        """Load configuration from file."""
        try:
            with open(self.config_path, 'r') as f:
                config = {}
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        key, value = [x.strip() for x in line.split('=', 1)]
                        config[key] = self._convert_value(value)
                
                self.__dict__.update(config)
        except Exception as e:
            logger.error(f"Failed to load rate limiting config: {e}")
            self._set_defaults()
            
    def _set_defaults(self):
        """Set default values if config loading fails."""
        self.INSTAGRAM_REQUESTS_PER_HOUR = 100
        self.INSTAGRAM_MIN_REQUEST_INTERVAL = 6
        self.INSTAGRAM_BATCH_DELAY = 30
        self.INSTAGRAM_MAX_BURST_REQUESTS = 3
        self.INITIAL_BACKOFF = 10
        self.MAX_BACKOFF = 1800
        self.BACKOFF_MULTIPLIER = 2
        self.BACKOFF_JITTER = 0.1
        self.SESSION_ROTATE_INTERVAL = 3600
        self.MAX_REQUESTS_PER_SESSION = 50
        self.ERROR_THRESHOLD = 5
        self.CONSERVATIVE_MODE_DURATION = 1800