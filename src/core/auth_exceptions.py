"""Authentication related exceptions."""

class TelegramAuthenticationRequired(Exception):
    """Raised when Telegram authentication is required."""
    pass

class TelegramAuthenticationInProgress(Exception):
    """Raised when Telegram authentication is already in progress."""
    pass