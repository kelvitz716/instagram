"""Error tracking and pattern detection."""

import time
import structlog
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import asyncio

logger = structlog.get_logger(__name__)

@dataclass
class ErrorPattern:
    """Represents a pattern of errors."""
    error_type: str
    component: str
    count: int = 0
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    error_messages: Set[str] = field(default_factory=set)
    
    def update(self, message: str) -> None:
        """Update the error pattern with a new occurrence."""
        self.count += 1
        self.last_seen = time.time()
        self.error_messages.add(message)

@dataclass
class ErrorThresholds:
    """Defines thresholds for error monitoring."""
    rate_window: float = 300  # 5 minutes
    rate_threshold: int = 10  # errors per window
    burst_threshold: int = 5  # errors in quick succession
    burst_window: float = 60  # 1 minute

class ErrorTracker:
    """
    Tracks errors and detects patterns in real-time.
    
    Features:
    - Error rate monitoring
    - Burst detection
    - Pattern recognition
    - Component health tracking
    """
    
    def __init__(
        self,
        thresholds: Optional[ErrorThresholds] = None,
        metrics_collector = None
    ):
        self.thresholds = thresholds or ErrorThresholds()
        self.metrics = metrics_collector
        self.patterns: Dict[Tuple[str, str], ErrorPattern] = {}
        self.recent_errors: List[Tuple[float, str, str]] = []
        self.component_health: Dict[str, bool] = defaultdict(lambda: True)
        self._stop_monitoring = asyncio.Event()
        self._monitor_task = None
        
    async def start(self) -> None:
        """Start error monitoring."""
        self._stop_monitoring.clear()
        self._monitor_task = asyncio.create_task(self._monitor_errors())
        logger.info("Started error monitoring")
        
    async def stop(self) -> None:
        """Stop error monitoring."""
        if self._monitor_task:
            self._stop_monitoring.set()
            await self._monitor_task
            self._monitor_task = None
        logger.info("Stopped error monitoring")
        
    def track_error(
        self,
        error_type: str,
        component: str,
        message: str,
        **context: dict
    ) -> None:
        """
        Track an error occurrence.
        
        Args:
            error_type: Type/category of the error
            component: Component where the error occurred
            message: Error message
            **context: Additional context about the error
        """
        now = time.time()
        
        # Update error patterns
        pattern_key = (error_type, component)
        if pattern_key not in self.patterns:
            self.patterns[pattern_key] = ErrorPattern(error_type, component)
        self.patterns[pattern_key].update(message)
        
        # Track recent errors
        self.recent_errors.append((now, error_type, component))
        
        # Clean up old errors
        cutoff = now - self.thresholds.rate_window
        self.recent_errors = [
            (t, et, c) for t, et, c in self.recent_errors
            if t > cutoff
        ]
        
        # Update metrics if available
        if self.metrics:
            self.metrics.record_error(error_type, component)
        
        # Log the error with context
        logger.error(
            "Error occurred",
            error_type=error_type,
            component=component,
            message=message,
            **context
        )
        
    def get_error_rate(
        self,
        error_type: Optional[str] = None,
        component: Optional[str] = None
    ) -> float:
        """Get the current error rate for the specified type/component."""
        now = time.time()
        window_start = now - self.thresholds.rate_window
        
        relevant_errors = [
            (t, et, c) for t, et, c in self.recent_errors
            if (t > window_start and
                (error_type is None or et == error_type) and
                (component is None or c == component))
        ]
        
        return len(relevant_errors) / self.thresholds.rate_window
    
    def detect_bursts(
        self,
        error_type: Optional[str] = None,
        component: Optional[str] = None
    ) -> bool:
        """Detect if there's a burst of errors occurring."""
        now = time.time()
        burst_start = now - self.thresholds.burst_window
        
        burst_errors = [
            (t, et, c) for t, et, c in self.recent_errors
            if (t > burst_start and
                (error_type is None or et == error_type) and
                (component is None or c == component))
        ]
        
        return len(burst_errors) >= self.thresholds.burst_threshold
    
    def get_component_health(self, component: str) -> bool:
        """Get the current health status of a component."""
        return self.component_health[component]
    
    async def _monitor_errors(self) -> None:
        """Background task to monitor errors and update component health."""
        while not self._stop_monitoring.is_set():
            try:
                # Check error rates for each component
                for (error_type, component), pattern in self.patterns.items():
                    rate = self.get_error_rate(error_type, component)
                    is_bursting = self.detect_bursts(error_type, component)
                    
                    # Update component health
                    self.component_health[component] = (
                        rate < self.thresholds.rate_threshold / self.thresholds.rate_window
                        and not is_bursting
                    )
                    
                    # Log if unhealthy
                    if not self.component_health[component]:
                        logger.warning(
                            "Component health degraded",
                            component=component,
                            error_type=error_type,
                            error_rate=rate,
                            is_bursting=is_bursting
                        )
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(
                    "Error in error monitoring task",
                    error=str(e),
                    exc_info=True
                )
                await asyncio.sleep(30)  # Back off on errors