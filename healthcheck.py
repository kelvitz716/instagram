#!/usr/bin/env python3
"""Enhanced health check system with detailed monitoring."""

import os
import sys
import json
import time
import psutil
import asyncio
import aiosqlite
import structlog
from typing import Dict, Any, List, Tuple
from pathlib import Path
from datetime import datetime, timedelta
from aiohttp import ClientSession, ClientTimeout

# Set up structured logging
logger = structlog.get_logger()

class HealthCheck:
    """
    Enhanced health check system with detailed component monitoring.
    
    Features:
    - Resource monitoring (CPU, memory, disk)
    - Service dependency checks
    - Performance metrics
    - Component health status
    - Detailed diagnostics
    """
    
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.downloads_path = base_path / 'downloads'
        self.data_path = base_path / 'data'
        self.temp_path = base_path / 'temp'
        
        # Health check thresholds
        self.disk_warning = 85
        self.disk_critical = 95
        self.memory_warning = 80
        self.memory_critical = 90
        self.cpu_warning = 80
        self.cpu_critical = 90
        
        # API timeouts
        self.timeout = ClientTimeout(total=5)
    
    async def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage."""
        try:
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Memory usage
            memory = psutil.virtual_memory()
            
            # Disk usage for each important directory
            disk_usage = {}
            for path_name, path in [
                ('downloads', self.downloads_path),
                ('data', self.data_path),
                ('temp', self.temp_path)
            ]:
                if path.exists():
                    usage = psutil.disk_usage(str(path))
                    disk_usage[path_name] = {
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': usage.percent
                    }
            
            return {
                'cpu': {
                    'percent': cpu_percent,
                    'status': self._get_status(cpu_percent, self.cpu_warning, self.cpu_critical)
                },
                'memory': {
                    'total': memory.total,
                    'available': memory.available,
                    'used': memory.used,
                    'percent': memory.percent,
                    'status': self._get_status(memory.percent, self.memory_warning, self.memory_critical)
                },
                'disk': {
                    path: {
                        **stats,
                        'status': self._get_status(stats['percent'], self.disk_warning, self.disk_critical)
                    }
                    for path, stats in disk_usage.items()
                }
            }
        except Exception as e:
            logger.error("Failed to check system resources", error=str(e))
            return {'error': str(e)}
    
    async def check_database(self) -> Dict[str, Any]:
        """Check database health and performance."""
        try:
            db_path = self.data_path / 'bot_data.db'
            if not db_path.exists():
                return {'status': 'error', 'message': 'Database file not found'}
            
            start_time = time.time()
            async with aiosqlite.connect(str(db_path)) as db:
                # Check if we can execute queries
                async with db.execute("SELECT 1") as cursor:
                    await cursor.fetchone()
                
                # Get database size
                async with db.execute("PRAGMA page_count") as cursor:
                    page_count = (await cursor.fetchone())[0]
                async with db.execute("PRAGMA page_size") as cursor:
                    page_size = (await cursor.fetchone())[0]
                
                # Calculate query latency
                latency = time.time() - start_time
                
                return {
                    'status': 'healthy',
                    'latency': latency,
                    'size': page_count * page_size,
                    'path': str(db_path)
                }
        except Exception as e:
            logger.error("Database health check failed", error=str(e))
            return {'status': 'error', 'message': str(e)}
    
    async def check_telegram_api(self) -> Dict[str, Any]:
        """Check Telegram API connectivity."""
        try:
            bot_token = os.getenv('BOT_TOKEN')
            if not bot_token:
                return {'status': 'error', 'message': 'BOT_TOKEN not found'}
            
            start_time = time.time()
            async with ClientSession(timeout=self.timeout) as session:
                async with session.get(
                    f'https://api.telegram.org/bot{bot_token}/getMe'
                ) as response:
                    data = await response.json()
                    latency = time.time() - start_time
                    
                    if data.get('ok'):
                        return {
                            'status': 'healthy',
                            'latency': latency,
                            'bot_info': data['result']
                        }
                    else:
                        return {
                            'status': 'error',
                            'message': data.get('description', 'Unknown error')
                        }
        except Exception as e:
            logger.error("Telegram API health check failed", error=str(e))
            return {'status': 'error', 'message': str(e)}
    
    async def check_components(self) -> Dict[str, Any]:
        """Check all component health statuses."""
        results = await asyncio.gather(
            self.check_system_resources(),
            self.check_database(),
            self.check_telegram_api(),
            return_exceptions=True
        )
        
        return {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'system': results[0] if not isinstance(results[0], Exception) else {'error': str(results[0])},
            'database': results[1] if not isinstance(results[1], Exception) else {'error': str(results[1])},
            'telegram_api': results[2] if not isinstance(results[2], Exception) else {'error': str(results[2])},
            'overall_status': self._determine_overall_status(results)
        }
    
    @staticmethod
    def _get_status(value: float, warning: float, critical: float) -> str:
        """Determine status based on thresholds."""
        if value >= critical:
            return 'critical'
        elif value >= warning:
            return 'warning'
        return 'healthy'
    
    @staticmethod
    def _determine_overall_status(results: List[Any]) -> str:
        """Determine overall system health status."""
        if any(isinstance(r, Exception) for r in results):
            return 'critical'
        
        status_priority = {'critical': 3, 'warning': 2, 'healthy': 1}
        current_status = 'healthy'
        
        for result in results:
            if isinstance(result, dict):
                if 'status' in result:
                    result_status = result['status']
                elif 'error' in result:
                    result_status = 'critical'
                else:
                    # Check nested components
                    nested_statuses = [
                        status.get('status', 'healthy')
                        for status in result.values()
                        if isinstance(status, dict)
                    ]
                    if nested_statuses:
                        result_status = max(
                            nested_statuses,
                            key=lambda s: status_priority.get(s, 0)
                        )
                    else:
                        continue
                
                if status_priority.get(result_status, 0) > status_priority.get(current_status, 0):
                    current_status = result_status
        
        return current_status

async def main():
    """Run health checks and exit with appropriate status code."""
    try:
        base_path = Path(__file__).parent
        health_check = HealthCheck(base_path)
        results = await health_check.check_components()
        
        # Print results in a structured format
        print(json.dumps(results, indent=2))
        
        # Exit with appropriate status code
        if results['overall_status'] == 'critical':
            sys.exit(2)
        elif results['overall_status'] == 'warning':
            sys.exit(1)
        else:
            sys.exit(0)
            
    except Exception as e:
        logger.error("Health check failed", error=str(e), exc_info=True)
        sys.exit(2)

if __name__ == '__main__':
    asyncio.run(main())