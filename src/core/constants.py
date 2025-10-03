"""Core constants for the Instagram bot."""

import re

# Content type icons
CONTENT_ICONS = {
    'post': '📷',
    'reel': '🎬', 
    'story': '📱',
    'highlight': '⭐',
    'profile': '👤',
    'tv': '📺',
    'unknown': '📄'
}

# URL patterns
BASE_INSTAGRAM = r'https?://(?:www\.)?'
INSTAGRAM_DOMAINS = ['instagram.com', 'instagr.am']
PATH_END = r'(?:/.*)?$'

# Pre-compiled regular expressions
URL_PATTERN = re.compile(r'https?://[^\s]+', re.I)
INSTAGRAM_URL_PATTERN = re.compile(
    f'{BASE_INSTAGRAM}(?:{"".join(f"(?:{domain})" for domain in INSTAGRAM_DOMAINS)})/[a-zA-Z0-9_/.-]+',
    re.I
)

# File size thresholds (in bytes)
MAX_BOT_API_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_TELETHON_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB
LARGE_FILE_THRESHOLD = 20 * 1024 * 1024  # 20MB

# Time constants (in seconds)
DEFAULT_TIMEOUT = 30
LONG_TIMEOUT = 300
CLEANUP_INTERVAL = 3600  # 1 hour
SESSION_EXPIRY = 86400 * 7  # 7 days

# Database constants
DEFAULT_POOL_SIZE = 5
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0

# Rate limiting constants
DEFAULT_RATE_LIMIT = {
    'requests_per_minute': 20,
    'burst_size': 5,
    'recovery_time': 60
}