from typing import Dict, List
import logging
from .interfaces import IAgentRegistry, IQualityManager, AgentContext, AgentResult
from .workflow_context import WorkflowContext
from .agent_registry import AgentRegistry
from .quality_manager import QualityManager
from .agent_factory import AgentFactory
from .circuit_breaker import CircuitBreakerManager
from .retry_manager import RetryManager

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class WorkflowRequest:
    def __init__(self, workflow_id: str, workflow_type: str, input_data: Dict):
        self.workflow_id = workflow_id
        self.workflow_type = workflow_type
        self.input_data = input_data

class WorkflowResult:
    def __init__(self, workflow_id: str, status: str, results: Dict, summary: Dict):
        self.workflow_id = workflow_id
        self.status = status
        self.results = results
        self.summary = summary
    
    @classmethod
    def from_context(cls, context: WorkflowContext):
        statuses = [r.status for r in context.agent_results.values()]
        if statuses and all(s == "success" for s in statuses):
            status = "completed"
        elif any(s == "success" for s in statuses):
            status = "partial"
        else:
            status = "failed"
        return cls(
            workflow_id=context.workflow_id,
            status=status,
            results={agent_id: result.data for agent_id, result in context.agent_results.items()},
            summary=context.get_execution_summary()
        )

class SupervisorAgent:
    """Clean supervisor following SOLID principles"""

    MAX_TRACKED_WORKFLOWS = 200
    
    def __init__(self, registry: IAgentRegistry, quality_manager: IQualityManager):
        self.registry = registry
        self.quality_manager = quality_manager
        self.circuit_breakers = CircuitBreakerManager()
        self.retry_manager = RetryManager()
        self.active_workflows: Dict[str, WorkflowContext] = {}
    
    def coordinate_workflow(self, request: WorkflowRequest) -> WorkflowResult:
        """Main coordination method"""
        logger.info(f"🎯 Starting workflow: {request.workflow_id}")
        
        context = WorkflowContext(request.workflow_id)
        context.set_shared_data("input_data", request.input_data)
        self.active_workflows[request.workflow_id] = context
        # Keep memory bounded: only the most recent workflows are queryable
        while len(self.active_workflows) > self.MAX_TRACKED_WORKFLOWS:
            self.active_workflows.pop(next(iter(self.active_workflows)))
        
        workflow_steps = self._get_workflow_steps(request.workflow_type)
        
        for step in workflow_steps:
            try:
                result = self._execute_step_with_protection(step, context)
                context.set_agent_result(step["agent_id"], result)
                
                quality_report = self.quality_manager.validate_agent_output(
                    step["agent_type"], result
                )
                
                logger.info(f"📊 Quality: {step['agent_id']} - {quality_report.grade}")
                
            except Exception as e:
                logger.error(f"❌ Step failed: {step['agent_id']} - {str(e)}")
                error_result = AgentResult(
                    status="error",
                    data={"error": str(e)},
                    confidence=0.0,
                    agent_id=step["agent_id"]
                )
                context.set_agent_result(step["agent_id"], error_result)
        
        result = WorkflowResult.from_context(context)
        logger.info(f"✅ Workflow {result.status}: {request.workflow_id}")
        return result
    
    def _execute_step_with_protection(self, step: Dict, context: WorkflowContext) -> AgentResult:
        """Execute step with circuit breaker and retry protection"""
        agent = self.registry.get_agent(step["agent_id"])
        if not agent:
            raise Exception(f"Agent not found: {step['agent_id']}")
        
        # Steps get the workflow's input plus any step-specific input (the
        # workflow input used to be stored but never passed to the agents)
        agent_context = AgentContext(
            input_data={**context.get_shared_data("input_data", {}), **step.get("input_data", {})},
            workflow_context=context,
            correlation_id=context.workflow_id
        )
        
        # Execute with protection
        return self.circuit_breakers.execute_with_breaker(
            step["agent_id"],
            lambda: self.retry_manager.execute_with_retry(
                step["agent_id"],
                agent.execute,
                agent_context
            )
        )
    
    def _get_workflow_steps(self, workflow_type: str) -> List[Dict]:
        """Get workflow steps"""
        workflows = {
            "contract_analysis": [
                {"agent_id": "pdf_processing", "agent_type": "pdf_processing"},
                {"agent_id": "clause_extraction", "agent_type": "clause_extraction"},
                {"agent_id": "risk_assessment", "agent_type": "risk_assessment"}
            ]
        }
        return workflows.get(workflow_type, [])
    
    def get_workflow_status(self, workflow_id: str) -> Dict:
        """Get workflow status"""
        context = self.active_workflows.get(workflow_id)
        if not context:
            return {"error": "Workflow not found"}
        return context.get_execution_summary()

class SupervisorFactory:
    @staticmethod
    def create_supervisor(llm_manager) -> SupervisorAgent:
        """Create supervisor with dependencies"""
        agent_factory = AgentFactory(llm_manager)
        registry = AgentRegistry()
        
        # Register agents
        for agent_type in agent_factory.get_available_types():
            agent = agent_factory.create_agent(agent_type)
            registry.register_agent(agent_type, agent)
        
        quality_manager = QualityManager()
        return SupervisorAgent(registry, quality_manager)