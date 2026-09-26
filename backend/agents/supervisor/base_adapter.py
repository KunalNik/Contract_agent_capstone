from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass
from .interfaces import IAgent, AgentContext, AgentResult

@dataclass
class AgentConfig:
    agent_id: str
    agent_type: str
    capabilities: List[str]
    config: Dict[str, Any] = None

class BaseAgentAdapter(IAgent):
    """Template method pattern for agent adapters"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.agent_id = config.agent_id
        self.agent_type = config.agent_type
    
    def execute(self, context: AgentContext) -> AgentResult:
        """Template method - same flow for all adapters.

        Unexpected exceptions propagate so the supervisor's retry manager and
        circuit breaker can act on them (swallowing them here made both dead
        code); the supervisor turns a final failure into an error result.
        """
        input_data = self.prepare_input(context)
        raw_result = self.call_agent(input_data)
        result = self.format_output(raw_result)
        result.agent_id = self.agent_id
        return result
    
    def get_capabilities(self) -> List[str]:
        return self.config.capabilities
    
    @abstractmethod
    def prepare_input(self, context: AgentContext) -> Dict[str, Any]:
        """Convert supervisor context to agent-specific input"""
        pass
    
    @abstractmethod
    def call_agent(self, input_data: Dict[str, Any]) -> Any:
        """Call the actual agent implementation"""
        pass
    
    @abstractmethod
    def format_output(self, raw_result: Any) -> AgentResult:
        """Convert agent output to standard format"""
        pass