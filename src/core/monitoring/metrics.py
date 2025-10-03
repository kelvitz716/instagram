"""Prometheus metrics collection and monitoring."""

from prometheus_client import (
    Counter, Gauge, Histogram, Summary,
    CollectorRegistry, start_http_server
)
from typing import Dict, Optional
import structlog
import psutil
import time

logger = structlog.get_logger(__name__)

class MetricsCollector:
    """Collect and expose metrics for the bot's operation."""
    
    def __init__(self, app_name: str = "instagram_bot"):
        self.app_name = app_name
        self.registry = CollectorRegistry()

    def get_metrics_as_text(self) -> str:
        """Get all metrics as text."""
        return generate_latest(self.registry).decode('utf-8')
        
        # Download/Upload metrics
        self.download_duration = Histogram(
            'download_duration_seconds',
            'Time spent downloading media',
            ['source', 'media_type'],
            registry=self.registry
        )
        self.upload_duration = Histogram(
            'upload_duration_seconds',
            'Time spent uploading media',
            ['destination', 'media_type'],
            registry=self.registry
        )
        
        # Resource metrics
        self.memory_usage = Gauge(
            'memory_usage_bytes',
            'Current memory usage',
            ['type'],
            registry=self.registry
        )
        self.disk_usage = Gauge(
            'disk_usage_bytes',
            'Current disk usage',
            ['path', 'type'],
            registry=self.registry
        )
        
        # API metrics
        self.api_requests = Counter(
            'api_requests_total',
            'Total API requests made',
            ['api', 'method', 'status'],
            registry=self.registry
        )
        self.api_latency = Summary(
            'api_request_latency_seconds',
            'API request latency',
            ['api', 'method'],
            registry=self.registry
        )
        
        # Queue metrics
        self.queue_size = Gauge(
            'queue_size',
            'Current size of processing queues',
            ['queue_name'],
            registry=self.registry
        )
        self.queue_processing_time = Histogram(
            'queue_processing_seconds',
            'Time spent processing queue items',
            ['queue_name'],
            registry=self.registry
        )
        
        # Error metrics
        self.errors_total = Counter(
            'errors_total',
            'Total number of errors',
            ['type', 'component'],
            registry=self.registry
        )
        
        # Session metrics
        self.active_sessions = Gauge(
            'active_sessions',
            'Number of active sessions',
            ['type'],
            registry=self.registry
        )
    
    def start_server(self, port: int = 8000) -> None:
        """Start the metrics server."""
        try:
            start_http_server(port, registry=self.registry)
            logger.info("Started metrics server", port=port)
        except Exception as e:
            logger.error("Failed to start metrics server", error=str(e))
    
    def track_download(self, source: str, media_type: str) -> "DownloadTimer":
        """Track download duration."""
        return DownloadTimer(self.download_duration, source, media_type)
    
    def track_upload(self, destination: str, media_type: str) -> "UploadTimer":
        """Track upload duration."""
        return UploadTimer(self.upload_duration, destination, media_type)
    
    def record_api_request(self, api: str, method: str, status: str) -> None:
        """Record an API request."""
        self.api_requests.labels(api=api, method=method, status=status).inc()
    
    def track_api_latency(self, api: str, method: str) -> "APITimer":
        """Track API request latency."""
        return APITimer(self.api_latency, api, method)
    
    def update_queue_size(self, queue_name: str, size: int) -> None:
        """Update queue size metric."""
        self.queue_size.labels(queue_name=queue_name).set(size)
    
    def track_queue_processing(self, queue_name: str) -> "QueueTimer":
        """Track queue processing time."""
        return QueueTimer(self.queue_processing_time, queue_name)
    
    def record_error(self, error_type: str, component: str) -> None:
        """Record an error occurrence."""
        self.errors_total.labels(type=error_type, component=component).inc()
    
    def update_session_count(self, session_type: str, count: int) -> None:
        """Update active session count."""
        self.active_sessions.labels(type=session_type).set(count)
    
    def update_resource_usage(self, paths: Optional[Dict[str, str]] = None) -> None:
        """Update resource usage metrics."""
        # Memory usage
        memory = psutil.virtual_memory()
        self.memory_usage.labels(type='total').set(memory.total)
        self.memory_usage.labels(type='used').set(memory.used)
        self.memory_usage.labels(type='available').set(memory.available)
        
        # Disk usage
        if paths:
            for name, path in paths.items():
                usage = psutil.disk_usage(path)
                self.disk_usage.labels(path=name, type='total').set(usage.total)
                self.disk_usage.labels(path=name, type='used').set(usage.used)
                self.disk_usage.labels(path=name, type='free').set(usage.free)

class Timer:
    """Base class for timing operations."""
    def __init__(self, metric, *label_values):
        self.metric = metric
        self.label_values = label_values
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            self.metric.labels(*self.label_values).observe(duration)

class DownloadTimer(Timer):
    """Context manager for timing downloads."""
    pass

class UploadTimer(Timer):
    """Context manager for timing uploads."""
    pass

class APITimer(Timer):
    """Context manager for timing API requests."""
    pass

class QueueTimer(Timer):
    """Context manager for timing queue processing."""
    pass