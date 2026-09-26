"""API endpoints for AI patterns functionality."""

from fastapi import APIRouter, HTTPException, Depends
from backend.governance.rbac import Permission, requires_permission
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

from backend.agents.patterns.pattern_orchestrator import PatternOrchestratorFactory

router = APIRouter(prefix="/api/patterns", tags=["AI Patterns"])


class PatternRequest(BaseModel):
    task_type: str = "analysis"
    patterns: List[str] = ["react", "cot", "rag"]
    query: str
    contract_text: Optional[str] = None
    contract_id: Optional[str] = None
    clauses: Optional[List[Dict[str, Any]]] = None
    policies: Optional[Dict[str, Any]] = None
    target_clause: Optional[str] = None
    max_iterations: int = Field(3, ge=1, le=10)


class PatternResponse(BaseModel):
    success: bool
    patterns_used: List[str]
    individual_results: Dict[str, Any]
    synthesized_result: Dict[str, Any]
    error: Optional[str] = None


@router.post("/analyze", response_model=PatternResponse, dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def analyze_with_patterns(request: PatternRequest):
    """Analyze contract using specified AI patterns."""
    try:
        orchestrator = PatternOrchestratorFactory.create_for_task(request.task_type)
        
        context = {
            'task_type': request.task_type,
            'patterns': request.patterns,
            'query': request.query,
            'contract_text': request.contract_text or '',
            'contract_id': request.contract_id or '',
            'clauses': request.clauses or [],
            'policies': request.policies or {},
            'target_clause': request.target_clause,
            'max_iterations': request.max_iterations,
        }
        
        result = await orchestrator.process(context)
        
        if result.get('success'):
            return PatternResponse(
                success=True,
                patterns_used=result.get('patterns_used', []),
                individual_results=result.get('individual_results', {}),
                synthesized_result=result.get('synthesized_result', {})
            )
        else:
            return PatternResponse(
                success=False,
                patterns_used=[],
                individual_results={},
                synthesized_result={},
                error=result.get('error', 'Unknown error')
            )
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/react", response_model=Dict[str, Any], dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def react_analysis(request: PatternRequest):
    """Perform ReACT pattern analysis only."""
    try:
        from backend.agents.patterns.react_agent import ReACTAgent
        
        agent = ReACTAgent(max_iterations=request.max_iterations)
        
        context = {
            'query': request.query,
            'contract_text': request.contract_text or '',
            'contract_id': request.contract_id or 'unknown'
        }
        
        return await agent.execute(context)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chain-of-thought", response_model=Dict[str, Any], dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def chain_of_thought_analysis(request: PatternRequest):
    """Perform Chain-of-Thought pattern analysis only."""
    try:
        from backend.agents.patterns.chain_of_thought_agent import ChainOfThoughtAgent
        
        agent = ChainOfThoughtAgent()
        
        context = {
            'task_type': request.task_type,
            'clauses': request.clauses or [],
            'policies': request.policies or {},
            'contract_text': request.contract_text or '',
            'target_clause': request.target_clause or request.query,
            'contract_id': request.contract_id or 'unknown'
        }
        
        return await agent.execute(context)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/advanced-rag", response_model=Dict[str, Any], dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def advanced_rag_analysis(request: PatternRequest):
    """Perform Advanced RAG pattern analysis only."""
    try:
        from backend.agents.patterns.advanced_rag_agent import AdvancedRAGAgent
        
        agent = AdvancedRAGAgent()
        
        context = {
            'query': request.query,
            'contract_id': request.contract_id or ''
        }
        
        result = await agent.process(context)
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/capabilities")
async def get_pattern_capabilities():
    """Get information about available AI patterns and their capabilities."""
    return {
        "available_patterns": {
            "react": {
                "name": "ReACT Pattern",
                "description": "Reasoning-Action-Observation cycles for iterative problem solving",
                "use_cases": ["clause_extraction", "iterative_analysis", "complex_queries"],
                "parameters": ["max_iterations", "query", "contract_text"]
            },
            "cot": {
                "name": "Chain-of-Thought Pattern", 
                "description": "Explicit step-by-step reasoning documentation",
                "use_cases": ["risk_assessment", "clause_analysis", "explainable_decisions"],
                "parameters": ["task_type", "clauses", "policies", "target_clause"]
            },
            "rag": {
                "name": "Advanced RAG Pattern",
                "description": "Sophisticated retrieval with precedent lookup and company history",
                "use_cases": ["contextual_analysis", "precedent_research", "comparative_analysis"],
                "parameters": ["query", "contract_id"]
            }
        },
        "task_types": {
            "risk_assessment": "Analyze contract risks and policy compliance",
            "clause_analysis": "Extract and analyze specific contract clauses",
            "analysis": "General contract analysis using all patterns"
        },
        "orchestration": {
            "description": "Combine multiple patterns for comprehensive analysis",
            "benefits": ["Higher accuracy", "Explainable results", "Contextual insights"]
        }
    }