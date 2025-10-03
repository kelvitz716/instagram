"""Structured logging configuration and setup."""

import sys
import logging
import structlog
import orjson
from typing import Any, Dict, Optional
from datetime import datetime
from pathlib import Path

from ..config import LoggingConfig

def serialize_datetime(dt: datetime) -> str:
    """Serialize datetime objects to ISO format."""
    return dt.isoformat() + "Z"

def serialize_to_json(obj: Any) -> str:
    """Custom JSON serializer that handles datetime objects."""
    return orjson.dumps(obj, default=serialize_datetime).decode('utf-8')

def setup_structured_logging(config: LoggingConfig) -> None:
    """Configure structured logging with the given configuration."""
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(serializer=serialize_to_json),
        ],
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(config.level)),
        cache_logger_on_first_use=True,
    )
    
    # Set up regular logging to integrate with structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=config.level,
    )

    # If a log file is specified, add a file handler
    if config.file:
        file_handler = logging.handlers.RotatingFileHandler(
            filename=config.file,
            maxBytes=config.max_file_size,
            backupCount=config.backup_count,
        )
        file_handler.setFormatter(logging.Formatter(config.format))
        logging.getLogger().addHandler(file_handler)

class RequestContext:
    """Context manager for request-specific logging context."""
    
    def __init__(
        self,
        request_id: str,
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
        **kwargs: Any
    ):
        self.context = {
            "request_id": request_id,
            "user_id": user_id,
            "chat_id": chat_id,
            **kwargs
        }
        self.logger = structlog.get_logger()

    def __enter__(self):
        # Bind context variables
        self.token = structlog.contextvars.bind_contextvars(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Clear context variables
        self.token.unbind()
        return False

class LoggerMixin:
    """Mixin to add structured logging capabilities to a class."""
    
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.logger = structlog.get_logger(self.__class__.__name__)
        
    def bind_logger(self, **kwargs: Any) -> None:
        """Bind additional context to the logger."""
        self.logger = self.logger.bind(**kwargs)