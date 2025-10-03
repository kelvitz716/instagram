"""Custom exceptions for the Instagram bot."""

class InstagramBotError(Exception):
    """Base exception for all bot errors."""
    pass

class ConfigurationError(InstagramBotError):
    """Raised when there is a configuration error."""
    pass

class DownloadError(InstagramBotError):
    """Raised when content download fails."""
    def __init__(self, message: str, url: str, retry_after: int = 0):
        super().__init__(message)
        self.url = url
        self.retry_after = retry_after

class UploadError(InstagramBotError):
    """Raised when content upload fails."""
    def __init__(self, message: str, file_path: str, is_large_file: bool = False):
        super().__init__(message)
        self.file_path = file_path
        self.is_large_file = is_large_file

class SessionError(InstagramBotError):
    """Raised when there are session-related issues."""
    pass

class RateLimitError(InstagramBotError):
    """Raised when rate limits are exceeded."""
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after

class ValidationError(InstagramBotError):
    """Raised when input validation fails."""
    pass

class DatabaseError(InstagramBotError):
    """Raised when database operations fail."""
    pass

class ResourceError(InstagramBotError):
    """Raised when resource management fails."""
    pass