"""Utility functions for parsing size strings with units."""
import re
from typing import Optional

def parse_size(size_str: str) -> Optional[int]:
    """Parse a size string with optional units (B, KB, MB, GB) into bytes.
    
    Args:
        size_str: Size string like "50MB" or "2GB" or "1024"
        
    Returns:
        Size in bytes or None if parsing fails
    """
    if not size_str:
        return None
        
    # If it's already a number without units, return it
    try:
        return int(size_str)
    except ValueError:
        pass
    
    # Parse number with units
    match = re.match(r'^(\d+)\s*([KMGT]?B)$', size_str.upper())
    if not match:
        return None
    
    number, unit = match.groups()
    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024,
        'TB': 1024 * 1024 * 1024 * 1024
    }
    
    return int(number) * multipliers.get(unit, 1)