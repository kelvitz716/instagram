import logging
from typing import Optional, Dict, Any, Callable
from datetime import datetime
import asyncio
from ..core.retry import RetryableOperation

logger = logging.getLogger(__name__)

class ProgressTracker:
    """Tracks progress of long-running operations"""
    
    def __init__(self):
        self._operations: Dict[str, Dict[str, Any]] = {}
        self._update_callbacks: Dict[str, Callable] = {}
        
    def start_operation(
        self, 
        operation_id: str, 
        total: Optional[int] = None,
        description: Optional[str] = None
    ):
        """Start tracking a new operation"""
        self._operations[operation_id] = {
            'current': 0,
            'total': total,
            'status': 'running',
            'description': description,
            'start_time': datetime.now(),
            'last_update': datetime.now(),
            'error': None
        }
        
    def update_progress(
        self, 
        operation_id: str, 
        current: int,
        total: Optional[int] = None,
        description: Optional[str] = None
    ):
        """Update progress of an operation"""
        if operation_id not in self._operations:
            logger.warning(f"Operation {operation_id} not found")
            return
            
        op = self._operations[operation_id]
        op['current'] = current
        if total is not None:
            op['total'] = total
        if description is not None:
            op['description'] = description
        op['last_update'] = datetime.now()
        
        # Call update callback if registered
        if operation_id in self._update_callbacks:
            try:
                self._update_callbacks[operation_id](self.get_progress(operation_id))
            except Exception as e:
                logger.error(f"Error in progress callback: {e}", exc_info=True)
    
    def complete_operation(self, operation_id: str, error: Optional[str] = None):
        """Mark an operation as complete"""
        if operation_id not in self._operations:
            logger.warning(f"Operation {operation_id} not found")
            return
            
        op = self._operations[operation_id]
        op['status'] = 'error' if error else 'complete'
        op['error'] = error
        op['last_update'] = datetime.now()
        
        # Call update callback if registered
        if operation_id in self._update_callbacks:
            try:
                self._update_callbacks[operation_id](self.get_progress(operation_id))
            except Exception as e:
                logger.error(f"Error in progress callback: {e}", exc_info=True)
            finally:
                del self._update_callbacks[operation_id]
    
    def get_progress(self, operation_id: str) -> Optional[Dict[str, Any]]:
        """Get current progress of an operation"""
        if operation_id not in self._operations:
            return None
            
        op = self._operations[operation_id]
        progress = op.copy()
        
        if progress['total']:
            progress['percentage'] = (progress['current'] / progress['total']) * 100
        else:
            progress['percentage'] = None
            
        progress['elapsed'] = (progress['last_update'] - progress['start_time']).total_seconds()
        
        return progress
    
    def register_callback(
        self, 
        operation_id: str, 
        callback: Callable[[Dict[str, Any]], None]
    ):
        """Register a callback for progress updates"""
        self._update_callbacks[operation_id] = callback
    
    @RetryableOperation()
    async def wait_for_completion(
        self, 
        operation_id: str,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Wait for an operation to complete
        
        Args:
            operation_id: ID of the operation to wait for
            timeout: Maximum time to wait in seconds
            
        Returns:
            bool: True if operation completed successfully, False if failed or timed out
        """
        start_time = datetime.now()
        
        while True:
            if operation_id not in self._operations:
                return False
                
            op = self._operations[operation_id]
            
            if op['status'] == 'complete':
                return True
            elif op['status'] == 'error':
                return False
                
            if timeout:
                elapsed = (datetime.now() - start_time).total_seconds()
                if elapsed >= timeout:
                    return False
                    
            await asyncio.sleep(0.1)  # Avoid busy waiting
    
    def cleanup_old_operations(self, max_age_seconds: int = 3600):
        """Remove completed operations older than max_age_seconds"""
        now = datetime.now()
        to_remove = []
        
        for op_id, op in self._operations.items():
            if op['status'] in ('complete', 'error'):
                age = (now - op['last_update']).total_seconds()
                if age > max_age_seconds:
                    to_remove.append(op_id)
                    
        for op_id in to_remove:
            del self._operations[op_id]
