"""Environment validation module for Instagram bot."""
import os
from pathlib import Path
from typing import Dict, List, Set, Any
import logging

logger = logging.getLogger(__name__)

# Required environment variables and their validation functions
REQUIRED_VARS: Dict[str, Any] = {
    'BOT_TOKEN': str,
    'API_ID': int,
    'API_HASH': str,
    'TARGET_CHAT_ID': int,
    'DATABASE_PATH': Path,
}

# Optional variables with their default values and types
OPTIONAL_VARS: Dict[str, tuple[Any, Any]] = {
    'ADMIN_USER_IDS': (str, ''),  # Comma-separated list
    'PHONE_NUMBER': (str, None),
    'SESSION_NAME': (str, 'telegram_bot_session'),
    'DATABASE_POOL_SIZE': (int, 5),
    'DATABASE_MAX_CONNECTIONS': (int, 10),
    'DATABASE_TIMEOUT': (int, 30),
    'DATABASE_WAL_MODE': (bool, True),
    'INSTAGRAM_USERNAME': (str, None),
    'COOKIES_FILE': (str, 'gallery-dl-cookies.txt'),
    'DOWNLOAD_TIMEOUT': (int, 300),
    'MAX_CONCURRENT_UPLOADS': (int, 3),
    'MAX_MESSAGES_PER_MINUTE': (int, 20),
    'DOWNLOADS_PATH': (str, 'downloads'),
    'UPLOADS_PATH': (str, 'uploads'),
    'TEMP_PATH': (str, 'temp'),
    'LOGS_PATH': (str, 'logs'),
    'CONFIG_PATH': (str, 'config'),
}

def validate_environment() -> List[str]:
    """
    Validate environment variables.
    
    Returns:
        List[str]: List of missing or invalid required variables.
    """
    missing: List[str] = []
    
    # Check required variables
    for var, var_type in REQUIRED_VARS.items():
        value = os.getenv(var)
        if not value:
            missing.append(var)
            continue
            
        try:
            # Try to convert to the required type
            if var_type == Path:
                Path(value)
            else:
                var_type(value)
        except (ValueError, TypeError):
            missing.append(f"{var} (invalid format)")
    
    # Check optional variables but don't require them
    for var, (var_type, default) in OPTIONAL_VARS.items():
        value = os.getenv(var)
        if value:
            try:
                if var_type == bool:
                    str(value).lower() in ('true', '1', 'yes', 'on')
                else:
                    var_type(value)
            except (ValueError, TypeError):
                missing.append(f"{var} (invalid format)")
    
    if missing:
        logger.error("Environment validation failed", missing_vars=missing)
    else:
        # Log successful configuration
        config = get_all_env_vars()
        logger.info("Environment configuration loaded", 
                   downloads_path=config.get('DOWNLOADS_PATH'),
                   database_path=config.get('DATABASE_PATH'),
                   instagram_username=config.get('INSTAGRAM_USERNAME'))
    
    return missing

def get_all_env_vars() -> Dict[str, str]:
    """
    Get all environment variables used by the bot.
    
    Returns:
        Dict[str, str]: Dictionary of environment variable names and their values.
    """
    env_vars = {}
    
    # Add required variables
    for var in REQUIRED_VARS:
        if var in os.environ:
            env_vars[var] = os.environ[var]
    
    # Add optional variables
    for var, (_, default) in OPTIONAL_VARS.items():
        env_vars[var] = os.environ.get(var, str(default) if default is not None else '')
    
    return env_vars

def validate_paths() -> List[str]:
    """
    Validate all required paths exist and are writable.
    
    Returns:
        List[str]: List of paths that are invalid or not writable.
    """
    invalid: List[str] = []
    paths_to_check = {
        'DOWNLOADS_PATH',
        'UPLOADS_PATH',
        'TEMP_PATH',
        'LOGS_PATH',
        'CONFIG_PATH',
    }
    
    for path_var in paths_to_check:
        path_str = os.getenv(path_var)
        if not path_str:
            continue
            
        path = Path(path_str)
        if not path.exists():
            try:
                path.mkdir(parents=True, exist_ok=True)
            except Exception:
                invalid.append(f"{path_var} (cannot create)")
        elif not os.access(path, os.W_OK):
            invalid.append(f"{path_var} (not writable)")
    
    return invalid

def validate_database() -> List[str]:
    """
    Validate database configuration.
    
    Returns:
        List[str]: List of database-related issues.
    """
    issues: List[str] = []
    
    db_path = os.getenv('DATABASE_PATH')
    if db_path:
        path = Path(db_path)
        
        # Check if parent directory exists and is writable
        if not path.parent.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                issues.append("DATABASE_PATH (parent directory cannot be created)")
        elif not os.access(path.parent, os.W_OK):
            issues.append("DATABASE_PATH (parent directory not writable)")
        
        # If database file exists, check if it's writable
        if path.exists() and not os.access(path, os.W_OK):
            issues.append("DATABASE_PATH (file not writable)")
    
    return issues