from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
from datetime import datetime

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class PlanningStrategy(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"
    RISK_FOCUSED = "risk_focused"
    COMPLIANCE_FOCUSED = "compliance_focused"

class StepType(str, Enum):
    EXTRACT_CLAUSES = "extract_clauses"
    CHECK_POLICIES = "check_policies"
    ASSESS_RISK = "assess_risk"
    GENERATE_REDLINES = "generate_redlines"
    VALIDATE_RESULTS = "validate_results"
    
    # CUAD mitigation steps (Phase 1)
    CUAD_MITIGATION = "cuad_mitigation"
    DEVIATION_ANALYSIS = "deviation_analysis"
    JURISDICTION_ADAPTATION = "jurisdiction_adaptation"
    PRECEDENT_MATCHING = "precedent_matching"

@dataclass
class ExecutionStep:
    step_id: str
    step_type: StepType
    description: str
    dependencies: List[str] = field(default_factory=list)
    expected_output: str = ""
    confidence_threshold: float = 0.8
    timeout_seconds: int = 30

@dataclass
class ExecutionPlan:
    plan_id: str
    query: str
    strategy: PlanningStrategy
    steps: List[ExecutionStep]
    estimated_duration: int
    confidence_score: float
    created_at: datetime = field(default_factory=datetime.now)

@dataclass
class ReasoningContext:
    query_complexity: float
    domain_keywords: List[str]
    user_intent: str
    available_agents: List[str]
    previous_results: Dict[str, Any] = field(default_factory=dict)

class IPlanningStrategy(ABC):
    @abstractmethod
    def create_plan(self, query: str, context: ReasoningContext) -> ExecutionPlan:
        pass

class SimplePlanningStrategy(IPlanningStrategy):
    def create_plan(self, query: str, context: ReasoningContext) -> ExecutionPlan:
        """Create simple sequential plan for basic queries"""
        steps = [
            ExecutionStep("step_1", StepType.EXTRACT_CLAUSES, "Extract key contract clauses"),
            ExecutionStep("step_2", StepType.CHECK_POLICIES, "Check policy compliance", ["step_1"]),
            ExecutionStep("step_3", StepType.ASSESS_RISK, "Calculate risk assessment", ["step_2"]),
            ExecutionStep("step_4", StepType.CUAD_MITIGATION, "CUAD deviation and jurisdiction analysis", ["step_3"]),
            ExecutionStep("step_5", StepType.GENERATE_REDLINES, "Generate redline suggestions", ["step_4"])
        ]
        
        return ExecutionPlan(
            plan_id=f"simple_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            query=query,
            strategy=PlanningStrategy.SIMPLE,
            steps=steps,
            estimated_duration=120,
            confidence_score=0.9
        )

class ComplexPlanningStrategy(IPlanningStrategy):
    def create_plan(self, query: str, context: ReasoningContext) -> ExecutionPlan:
        """Create sophisticated plan with parallel execution and validation"""
        steps = [
            ExecutionStep("step_1", StepType.EXTRACT_CLAUSES, "Deep clause extraction with validation"),
            ExecutionStep("step_2a", StepType.CHECK_POLICIES, "Policy compliance check", ["step_1"]),
            ExecutionStep("step_2b", StepType.ASSESS_RISK, "Initial risk assessment", ["step_1"]),
            ExecutionStep("step_3", StepType.CUAD_MITIGATION, "CUAD deviation and jurisdiction analysis", ["step_2a", "step_2b"]),
            ExecutionStep("step_4", StepType.VALIDATE_RESULTS, "Cross-validate results", ["step_3"]),
            ExecutionStep("step_5", StepType.GENERATE_REDLINES, "Generate comprehensive redlines", ["step_4"])
        ]
        
        return ExecutionPlan(
            plan_id=f"complex_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            query=query,
            strategy=PlanningStrategy.COMPLEX,
            steps=steps,
            estimated_duration=180,
            confidence_score=0.95
        )

class QueryAnalyzer:
    """Analyze query complexity and determine optimal strategy"""
    
    def analyze_query(self, query: str) -> ReasoningContext:
        complexity_indicators = [
            "compare", "analyze", "comprehensive", "detailed", "all", "every"
        ]
        
        risk_keywords = ["risk", "liability", "exposure", "dangerous", "critical"]
        compliance_keywords = ["policy", "compliance", "regulation", "standard", "requirement"]
        
        complexity = sum(1 for indicator in complexity_indicators if indicator in query.lower()) / len(complexity_indicators)
        
        domain_keywords = []
        user_intent = "analysis"
        
        if any(keyword in query.lower() for keyword in risk_keywords):
            domain_keywords.extend(risk_keywords)
            user_intent = "risk_assessment"
        
        if any(keyword in query.lower() for keyword in compliance_keywords):
            domain_keywords.extend(compliance_keywords)
            user_intent = "compliance_check"
        
        return ReasoningContext(
            query_complexity=complexity,
            domain_keywords=domain_keywords,
            user_intent=user_intent,
            available_agents=["clause_extractor", "policy_checker", "risk_assessor", "redline_generator"]
        )

class PlanningAgent:
    """Autonomous Planning & Reasoning Agent"""

    # Process-wide counter (instances are created per analysis)
    total_plans_created = 0
    
    def __init__(self):
        self.strategies = {
            PlanningStrategy.SIMPLE: SimplePlanningStrategy(),
            PlanningStrategy.COMPLEX: ComplexPlanningStrategy(),
            PlanningStrategy.RISK_FOCUSED: ComplexPlanningStrategy(),  # Use complex for risk-focused
            PlanningStrategy.COMPLIANCE_FOCUSED: ComplexPlanningStrategy()  # Use complex for compliance-focused
        }
        self.query_analyzer = QueryAnalyzer()
        self.execution_history: List[ExecutionPlan] = []
    
    def create_execution_plan(self, query: str) -> ExecutionPlan:
        """Main entry point - analyze query and create optimal execution plan"""
        logger.info(f"🧠 Planning Agent: Analyzing query: {query}")
        
        # Analyze query to understand requirements
        context = self.query_analyzer.analyze_query(query)
        
        # Select optimal strategy based on analysis
        strategy = self._select_strategy(context)
        
        # Create execution plan
        plan = self.strategies[strategy].create_plan(query, context)
        
        # Self-reflection and validation
        validated_plan = self._validate_and_refine_plan(plan, context)
        
        # Store for learning
        self.execution_history.append(validated_plan)
        PlanningAgent.total_plans_created += 1
        
        logger.info(f"🧠 Planning Agent: Created {strategy} plan with {len(validated_plan.steps)} steps")
        return validated_plan
    
    def _select_strategy(self, context: ReasoningContext) -> PlanningStrategy:
        """Select optimal planning strategy based on context"""
        if context.query_complexity > 0.6:
            return PlanningStrategy.COMPLEX
        elif "risk" in context.user_intent:
            return PlanningStrategy.RISK_FOCUSED
        elif "compliance" in context.user_intent:
            return PlanningStrategy.COMPLIANCE_FOCUSED
        else:
            return PlanningStrategy.SIMPLE
    
    def _validate_and_refine_plan(self, plan: ExecutionPlan, context: ReasoningContext) -> ExecutionPlan:
        """Self-reflection: validate and refine the execution plan"""
        
        # Check for missing dependencies
        step_ids = {step.step_id for step in plan.steps}
        for step in plan.steps:
            for dep in step.dependencies:
                if dep not in step_ids:
                    logger.warning(f"🧠 Planning Agent: Missing dependency {dep} for step {step.step_id}")
        
        # Adjust confidence based on complexity
        if context.query_complexity > 0.8 and plan.confidence_score > 0.9:
            plan.confidence_score = 0.85  # Lower confidence for very complex queries
        
        # Add validation step for high-risk scenarios
        if "risk" in context.user_intent and not any(step.step_type == StepType.VALIDATE_RESULTS for step in plan.steps):
            validation_step = ExecutionStep(
                "validation", 
                StepType.VALIDATE_RESULTS, 
                "Validate risk assessment results",
                [step.step_id for step in plan.steps[-2:]]
            )
            plan.steps.append(validation_step)
        
        return plan
    
    def adapt_plan_from_feedback(self, plan_id: str, execution_results: Dict[str, Any]) -> None:
        """Learn from execution results to improve future planning"""
        # Find the executed plan
        executed_plan = next((p for p in self.execution_history if p.plan_id == plan_id), None)
        if not executed_plan:
            return
        
        # Analyze results and adapt strategies
        success_rate = execution_results.get("success_rate", 0.0)
        if success_rate < 0.8:
            logger.info(f"🧠 Planning Agent: Learning from low success rate ({success_rate}) for plan {plan_id}")
            # Future enhancement: Update strategy weights based on performance
    
    def get_plan_status(self, plan_id: str) -> Dict[str, Any]:
        """Get status of a specific execution plan"""
        plan = next((p for p in self.execution_history if p.plan_id == plan_id), None)
        if not plan:
            return {"error": "Plan not found"}
        
        return {
            "plan_id": plan.plan_id,
            "strategy": plan.strategy,
            "steps_count": len(plan.steps),
            "estimated_duration": plan.estimated_duration,
            "confidence_score": plan.confidence_score,
            "created_at": plan.created_at.isoformat()
        }

# Factory for creating planning agents
class PlanningAgentFactory:
    @staticmethod
    def create_planning_agent() -> PlanningAgent:
        """Create a new planning agent instance"""
        return PlanningAgent()