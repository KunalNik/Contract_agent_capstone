import time
import logging
from typing import Dict, Any, Optional
from functools import wraps
from datetime import datetime, timedelta
from dataclasses import dataclass, field
import threading

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

@dataclass
class PerformanceMetric:
    """Performance metric data"""
    operation: str
    duration_ms: float
    timestamp: datetime
    success: bool
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class PerformanceMonitor:
    """Real-time performance monitoring"""
    
    def __init__(self):
        self.metrics: Dict[str, list] = {}
        self.lock = threading.Lock()
        self.alert_thresholds = {
            "cuad_analysis": 5000,  # 5 seconds
            "deviation_detection": 2000,  # 2 seconds
            "precedent_matching": 3000,  # 3 seconds
            "jurisdiction_adaptation": 1000  # 1 second
        }
    
    def record_metric(self, metric: PerformanceMetric):
        """Record performance metric"""
        with self.lock:
            if metric.operation not in self.metrics:
                self.metrics[metric.operation] = []
            
            self.metrics[metric.operation].append(metric)
            
            # Keep only last 100 metrics per operation
            if len(self.metrics[metric.operation]) > 100:
                self.metrics[metric.operation] = self.metrics[metric.operation][-100:]
            
            # Check for performance alerts
            self._check_performance_alert(metric)
    
    def _check_performance_alert(self, metric: PerformanceMetric):
        """Check if metric exceeds alert threshold"""
        threshold = self.alert_thresholds.get(metric.operation)
        if threshold and metric.duration_ms > threshold:
            logger.warning(
                f"Performance alert: {metric.operation} took {metric.duration_ms:.0f}ms "
                f"(threshold: {threshold}ms)"
            )
    
    def get_stats(self, operation: str, hours: int = 1) -> Dict[str, Any]:
        """Get performance statistics for operation"""
        with self.lock:
            if operation not in self.metrics:
                return {"error": "No metrics found"}
            
            # Filter metrics by time window
            cutoff = datetime.now() - timedelta(hours=hours)
            recent_metrics = [
                m for m in self.metrics[operation] 
                if m.timestamp > cutoff
            ]
            
            if not recent_metrics:
                return {"error": "No recent metrics"}
            
            durations = [m.duration_ms for m in recent_metrics]
            success_count = sum(1 for m in recent_metrics if m.success)
            
            return {
                "operation": operation,
                "total_calls": len(recent_metrics),
                "success_rate": success_count / len(recent_metrics),
                "avg_duration_ms": sum(durations) / len(durations),
                "min_duration_ms": min(durations),
                "max_duration_ms": max(durations),
                "p95_duration_ms": sorted(durations)[int(len(durations) * 0.95)] if durations else 0,
                "error_count": len(recent_metrics) - success_count
            }
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all operations"""
        return {op: self.get_stats(op) for op in self.metrics.keys()}

# Global monitor instance
monitor = PerformanceMonitor()

def track_performance(operation: str):
    """Decorator to track function performance (sync and async functions).

    The old sync-only wrapper timed coroutine *creation* (~0 ms) and always
    recorded success for async functions.
    """
    import asyncio as _asyncio

    def record(func, start_time, success, error_message):
        monitor.record_metric(PerformanceMetric(
            operation=operation,
            duration_ms=(time.time() - start_time) * 1000,
            timestamp=datetime.now(),
            success=success,
            error_message=error_message,
            metadata={"function": func.__name__}
        ))

    def decorator(func):
        if _asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                try:
                    result = await func(*args, **kwargs)
                except Exception as e:
                    record(func, start_time, False, str(e))
                    raise
                record(func, start_time, True, None)
                return result
            return async_wrapper

        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
            except Exception as e:
                record(func, start_time, False, str(e))
                raise
            record(func, start_time, True, None)
            return result

        return wrapper
    return decorator
