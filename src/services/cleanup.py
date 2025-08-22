"""Service for managing download directory cleanup."""

import os
import logging
import shutil
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class CleanupService:
    """Manages cleanup of old download directories."""
    
    def __init__(self, downloads_path: str, max_age_days: int = 7):
        self.downloads_path = Path(downloads_path)
        self.max_age_days = max_age_days
        
    def is_directory_old(self, dir_path: Path) -> bool:
        """Check if a directory is older than max_age_days."""
        try:
            # Get directory creation time
            dir_time = datetime.fromtimestamp(os.path.getctime(dir_path))
            age = datetime.now() - dir_time
            return age > timedelta(days=self.max_age_days)
        except Exception as e:
            logger.error(f"Error checking directory age for {dir_path}: {e}")
            return False
            
    def get_directory_size(self, dir_path: Path) -> int:
        """Get total size of directory in bytes."""
        try:
            total = 0
            with os.scandir(dir_path) as it:
                for entry in it:
                    if entry.is_file():
                        total += entry.stat().st_size
                    elif entry.is_dir():
                        total += self.get_directory_size(Path(entry.path))
            return total
        except Exception as e:
            logger.error(f"Error calculating directory size for {dir_path}: {e}")
            return 0
            
    def cleanup_old_directories(self) -> tuple[int, int]:
        """
        Clean up old download directories.
        Returns tuple of (number of directories removed, total bytes freed)
        """
        if not self.downloads_path.exists():
            return 0, 0
            
        dirs_removed = 0
        total_bytes_freed = 0
        
        try:
            # Iterate through all download directories
            for item in self.downloads_path.iterdir():
                if not item.is_dir():
                    continue
                    
                if self.is_directory_old(item):
                    try:
                        size = self.get_directory_size(item)
                        shutil.rmtree(item)
                        dirs_removed += 1
                        total_bytes_freed += size
                        logger.info(f"Removed old directory: {item} (freed {size/1024/1024:.2f} MB)")
                    except Exception as e:
                        logger.error(f"Error removing directory {item}: {e}")
                        
            return dirs_removed, total_bytes_freed
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0, 0
            
    def get_storage_stats(self) -> dict:
        """Get storage statistics for downloads directory."""
        try:
            total_size = self.get_directory_size(self.downloads_path)
            num_dirs = sum(1 for item in self.downloads_path.iterdir() if item.is_dir())
            
            # Get counts of old vs new directories
            old_dirs = sum(1 for item in self.downloads_path.iterdir() 
                         if item.is_dir() and self.is_directory_old(item))
                         
            return {
                "total_size_mb": total_size / 1024 / 1024,
                "total_directories": num_dirs,
                "old_directories": old_dirs,
                "clean_directories": num_dirs - old_dirs
            }
        except Exception as e:
            logger.error(f"Error getting storage stats: {e}")
            return {}
