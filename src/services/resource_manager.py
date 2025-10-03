"""Resource management service for monitoring and optimizing system resources."""

import os
import psutil
import logging
import asyncio
import shutil
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta

from ..core.config import BotConfig
from .cleanup import CleanupService
from .database import DatabaseService
from .telegram_session_storage import TelegramSessionStorage
from .session_storage import SessionStorageService

logger = logging.getLogger(__name__)

class ResourceManager:
    """
    Manages system resources including:
    - Session rotation and cleanup
    - Disk space monitoring and cleanup
    - Memory usage optimization
    - Connection pool management
    """
    
    def __init__(
        self,
        config: BotConfig,
        db_service: DatabaseService,
        cleanup_service: CleanupService,
        telegram_session_storage: TelegramSessionStorage,
        instagram_session_storage: SessionStorageService
    ):
        self.config = config
        self.db_service = db_service
        self.cleanup_service = cleanup_service
        self.telegram_session_storage = telegram_session_storage
        self.instagram_session_storage = instagram_session_storage
        
        # Resource thresholds
        self.disk_warning_threshold = 0.85  # 85% disk usage
        self.disk_critical_threshold = 0.95  # 95% disk usage
        self.memory_warning_threshold = 0.80  # 80% memory usage
        self.memory_critical_threshold = 0.90  # 90% memory usage
        
        # Session rotation settings
        self.session_max_age = timedelta(days=7)  # Rotate sessions weekly
        self.session_cleanup_interval = timedelta(days=1)  # Clean up daily
        
        # Initialize monitoring tasks
        self.monitoring_tasks = []
        self._stop_monitoring = asyncio.Event()

    async def start_monitoring(self):
        """Start all resource monitoring tasks."""
        self.monitoring_tasks = [
            asyncio.create_task(self._monitor_disk_space()),
            asyncio.create_task(self._monitor_memory_usage()),
            asyncio.create_task(self._monitor_sessions()),
            asyncio.create_task(self._cleanup_temp_files())
        ]
        
    async def stop_monitoring(self):
        """Stop all monitoring tasks."""
        self._stop_monitoring.set()
        for task in self.monitoring_tasks:
            task.cancel()
        await asyncio.gather(*self.monitoring_tasks, return_exceptions=True)
        
    async def _monitor_disk_space(self):
        """Monitor disk space and trigger cleanup when needed."""
        while not self._stop_monitoring.is_set():
            try:
                disk_usage = psutil.disk_usage(self.config.downloads_path)
                disk_percent = disk_usage.percent / 100
                
                if disk_percent >= self.disk_critical_threshold:
                    logger.warning("Disk usage critical, performing emergency cleanup")
                    await self._emergency_cleanup()
                elif disk_percent >= self.disk_warning_threshold:
                    logger.info("Disk usage high, performing regular cleanup")
                    await self._regular_cleanup()
                    
                # Check disk space every 5 minutes
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error monitoring disk space: {e}")
                await asyncio.sleep(60)
                
    async def _monitor_memory_usage(self):
        """Monitor memory usage and optimize when needed."""
        while not self._stop_monitoring.is_set():
            try:
                memory = psutil.virtual_memory()
                memory_percent = memory.percent / 100
                
                if memory_percent >= self.memory_critical_threshold:
                    logger.warning("Memory usage critical, performing optimization")
                    await self._optimize_memory()
                elif memory_percent >= self.memory_warning_threshold:
                    logger.info("Memory usage high, performing light optimization")
                    await self._light_optimize_memory()
                    
                # Check memory every minute
                await asyncio.sleep(60)
                
            except Exception as e:
                logger.error(f"Error monitoring memory: {e}")
                await asyncio.sleep(60)
                
    async def _monitor_sessions(self):
        """Monitor and rotate sessions as needed."""
        while not self._stop_monitoring.is_set():
            try:
                # Clean up old sessions
                telegram_cleaned = await self.telegram_session_storage.cleanup_old_sessions()
                instagram_cleaned = await self.instagram_session_storage.cleanup_expired_sessions()
                
                if telegram_cleaned or instagram_cleaned:
                    logger.info(f"Cleaned up {telegram_cleaned} Telegram and {instagram_cleaned} Instagram sessions")
                    
                # Check sessions every hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error monitoring sessions: {e}")
                await asyncio.sleep(300)
                
    async def _cleanup_temp_files(self):
        """Periodically clean up temporary files."""
        while not self._stop_monitoring.is_set():
            try:
                temp_path = self.config.temp_path
                if temp_path.exists():
                    # Remove files older than 24 hours
                    cutoff = datetime.now() - timedelta(hours=24)
                    removed = 0
                    total_size = 0
                    
                    for item in temp_path.iterdir():
                        try:
                            if item.stat().st_mtime < cutoff.timestamp():
                                size = item.stat().st_size
                                if item.is_file():
                                    item.unlink()
                                else:
                                    shutil.rmtree(item)
                                removed += 1
                                total_size += size
                        except Exception as e:
                            logger.error(f"Error removing temp file {item}: {e}")
                            
                    if removed:
                        logger.info(f"Cleaned up {removed} temp files ({total_size/1024/1024:.1f}MB)")
                        
                # Check temp files every 30 minutes
                await asyncio.sleep(1800)
                
            except Exception as e:
                logger.error(f"Error cleaning temp files: {e}")
                await asyncio.sleep(300)
                
    async def _emergency_cleanup(self):
        """Perform emergency cleanup when disk space is critical."""
        try:
            # Clean up all temp files
            if self.config.temp_path.exists():
                shutil.rmtree(self.config.temp_path)
                self.config.temp_path.mkdir(exist_ok=True)
                
            # Force cleanup of all old media
            dirs_removed, bytes_freed = await self.cleanup_service.cleanup_all_media()
            logger.info(f"Emergency cleanup: removed {dirs_removed} dirs, freed {bytes_freed/1024/1024:.1f}MB")
            
            # Vacuum database
            await self.db_service.vacuum()
            
        except Exception as e:
            logger.error(f"Error during emergency cleanup: {e}")
            
    async def _regular_cleanup(self):
        """Perform regular cleanup when disk space is high."""
        try:
            # Clean up old directories
            dirs_removed, bytes_freed = await self.cleanup_service.cleanup_old_directories()
            if dirs_removed:
                logger.info(f"Regular cleanup: removed {dirs_removed} dirs, freed {bytes_freed/1024/1024:.1f}MB")
                
        except Exception as e:
            logger.error(f"Error during regular cleanup: {e}")
            
    async def _optimize_memory(self):
        """Perform full memory optimization."""
        try:
            # Clear connection pools
            await self.db_service.clear_pools()
            
            # Force garbage collection
            import gc
            gc.collect()
            
            # Clear any file handles
            import gc
            for obj in gc.get_objects():
                try:
                    if hasattr(obj, 'close') and hasattr(obj, 'closed') and not obj.closed:
                        obj.close()
                except Exception:
                    pass
                    
        except Exception as e:
            logger.error(f"Error during memory optimization: {e}")
            
    async def _light_optimize_memory(self):
        """Perform light memory optimization."""
        try:
            # Just run garbage collection
            import gc
            gc.collect()
        except Exception as e:
            logger.error(f"Error during light memory optimization: {e}")
            
    async def get_resource_stats(self) -> Dict:
        """Get current resource statistics."""
        try:
            stats = {
                "disk_usage": psutil.disk_usage(self.config.downloads_path)._asdict(),
                "memory_usage": psutil.virtual_memory()._asdict(),
                "storage": self.cleanup_service.get_storage_stats(),
                "connections": {
                    "db_pool_size": await self.db_service.get_pool_size(),
                },
                "sessions": {
                    "telegram": await self.telegram_session_storage.get_active_session() is not None,
                    "instagram": await self.instagram_session_storage.get_session_count()
                }
            }
            return stats
        except Exception as e:
            logger.error(f"Error getting resource stats: {e}")
            return {}