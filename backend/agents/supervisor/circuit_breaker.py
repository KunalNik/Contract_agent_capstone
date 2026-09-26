from typing import Dict, Callable, Any
from dataclasses import dataclass
from enum import Enum
import logging
from datetime import datetime, timedelta

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open" # Testing recovery

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds
    success_threshold: int = 3

class CircuitBreaker:
    def __init__(self, agent_id: str, config: CircuitBreakerConfig = None):
        self.agent_id = agent_id
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info(f"🔄 Circuit breaker HALF_OPEN for {self.agent_id}")
            else:
                raise Exception(f"Circuit breaker OPEN for {self.agent_id}")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        """Handle successful execution"""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.config.success_threshold:
                self._reset()
        else:
            self.failure_count = 0
    
    def _on_failure(self):
        """Handle failed execution"""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            logger.error(f"🚨 Circuit breaker OPEN for {self.agent_id}")
    
    def _should_attempt_reset(self) -> bool:
        """Check if should attempt reset"""
        if not self.last_failure_time:
            return False
        
        # total_seconds(): .seconds ignores whole days and wraps every 24h
        return (datetime.now() - self.last_failure_time).total_seconds() >= self.config.recovery_timeout
    
    def _reset(self):
        """Reset circuit breaker to normal operation"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        logger.info(f"✅ Circuit breaker CLOSED for {self.agent_id}")

class CircuitBreakerManager:
    def __init__(self):
        self.breakers: Dict[str, CircuitBreaker] = {}
    
    def get_breaker(self, agent_id: str) -> CircuitBreaker:
        """Get or create circuit breaker for agent"""
        if agent_id not in self.breakers:
            self.breakers[agent_id] = CircuitBreaker(agent_id)
        return self.breakers[agent_id]
    
    def execute_with_breaker(self, agent_id: str, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection"""
        breaker = self.get_breaker(agent_id)
        return breaker.call(func, *args, **kwargs)
    
    def get_status(self) -> Dict[str, str]:
        """Get status of all circuit breakers"""
        return {agent_id: breaker.state.value for agent_id, breaker in self.breakers.items()}