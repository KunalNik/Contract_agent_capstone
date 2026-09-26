from fastapi import APIRouter, HTTPException, Depends, Request
from backend.governance.rbac import Permission, requires_permission, get_current_tenant
from typing import Literal
from pydantic import BaseModel, Field
from typing import Dict, List, Any, Optional
from datetime import datetime
import uuid
import logging
from backend.agents.feedback_learning_system import FeedbackCollector, LegalDecision, AdaptiveAnalyzer

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["legal-feedback"])

class LegalDecisionRequest(BaseModel):
    contract_id: str
    clause_id: str
    clause_type: str
    original_analysis: Dict[str, Any]
    legal_decision: Literal["approved", "rejected", "modified"]
    legal_feedback: str
    risk_assessment_override: Optional[str] = None
    confidence_score: Optional[float] = Field(0.0, ge=0.0, le=1.0)

class FeedbackResponse(BaseModel):
    decision_id: str
    status: str
    message: str

@router.post("/legal-decision", response_model=FeedbackResponse, dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def submit_legal_decision(request: LegalDecisionRequest, tenant_id: str = Depends(get_current_tenant)):
    """Submit legal team decision for learning"""
    try:
        # Create legal decision
        decision = LegalDecision(
            decision_id=str(uuid.uuid4()),
            contract_id=request.contract_id,
            clause_id=request.clause_id,
            clause_type=request.clause_type,
            original_analysis=request.original_analysis,
            legal_decision=request.legal_decision,
            legal_feedback=request.legal_feedback,
            risk_assessment_override=request.risk_assessment_override,
            confidence_score=request.confidence_score or 0.0,
            decision_timestamp=datetime.now(),
            tenant_id=tenant_id
        )
        
        # Store decision (raises if the contract is not the caller's or the write fails)
        collector = FeedbackCollector()
        collector.collect_decision(decision)
        
        logger.info(f"Legal decision submitted: {decision.decision_id}")
        
        return FeedbackResponse(
            decision_id=decision.decision_id,
            status="success",
            message="Legal decision recorded successfully"
        )
        
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to submit legal decision: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to record decision: {str(e)}")

@router.get("/decisions/{contract_id}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_contract_decisions(contract_id: str, tenant_id: str = Depends(get_current_tenant)):
    """Get all legal decisions for a contract"""
    try:
        collector = FeedbackCollector()
        
        # Query decisions for contract
        query = """
        MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})-[:HAS_DECISION]->(d:LegalDecision)
        RETURN d
        ORDER BY d.decision_timestamp DESC
        """
        
        from backend.infrastructure.contract_repository import Neo4jContractRepository
        repository = Neo4jContractRepository()
        results = repository.graph.query(query, {"contract_id": contract_id, "tenant_id": tenant_id})
        
        decisions = []
        for result in results:
            d = result["d"]
            decisions.append({
                "decision_id": d.get("decision_id"),
                "clause_id": d.get("clause_id"),
                "clause_type": d.get("clause_type"),
                "legal_decision": d.get("legal_decision"),
                "legal_feedback": d.get("legal_feedback"),
                "risk_assessment_override": d.get("risk_assessment_override"),
                "confidence_score": d.get("confidence_score", 0.0),
                "decision_timestamp": d.get("decision_timestamp")
            })
        
        return {
            "contract_id": contract_id,
            "decisions": decisions,
            "total_decisions": len(decisions)
        }
        
    except Exception as e:
        logger.error(f"Failed to get decisions for contract {contract_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve decisions: {str(e)}")

@router.get("/patterns/{clause_type}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_learned_patterns(clause_type: str, tenant_id: str = Depends(get_current_tenant)):
    """Get learned patterns for a clause type"""
    try:
        analyzer = AdaptiveAnalyzer(tenant_id=tenant_id)
        analyzer.load_patterns_for_clause_type(clause_type)
        
        patterns = analyzer.active_patterns.get(clause_type, [])
        
        pattern_data = []
        for pattern in patterns:
            pattern_data.append({
                "pattern_id": pattern.pattern_id,
                "pattern_type": pattern.pattern_type,
                "conditions": pattern.conditions,
                "learned_outcome": pattern.learned_outcome,
                "confidence": pattern.confidence,
                "usage_count": pattern.usage_count,
                "success_rate": pattern.success_rate
            })
        
        return {
            "clause_type": clause_type,
            "patterns": pattern_data,
            "total_patterns": len(pattern_data)
        }
        
    except Exception as e:
        logger.error(f"Failed to get patterns for clause type {clause_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve patterns: {str(e)}")

@router.post("/retrain/{clause_type}", dependencies=[Depends(requires_permission(Permission.MANAGE_POLICIES))])
async def retrain_patterns(clause_type: str, tenant_id: str = Depends(get_current_tenant)):
    """Retrain patterns for a specific clause type"""
    try:
        analyzer = AdaptiveAnalyzer(tenant_id=tenant_id)
        patterns = analyzer.pattern_learner.learn_from_decisions(clause_type)
        
        return {
            "clause_type": clause_type,
            "new_patterns_learned": len(patterns),
            "patterns": [
                {
                    "pattern_id": p.pattern_id,
                    "pattern_type": p.pattern_type,
                    "confidence": p.confidence
                }
                for p in patterns
            ]
        }
        
    except Exception as e:
        logger.error(f"Failed to retrain patterns for {clause_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Retraining failed: {str(e)}")

@router.get("/analytics/dashboard", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_feedback_analytics(tenant_id: str = Depends(get_current_tenant)):
    """Get feedback analytics for dashboard"""
    try:
        from backend.infrastructure.contract_repository import Neo4jContractRepository
        repository = Neo4jContractRepository()
        
        # Get feedback statistics
        query = """
        MATCH (d:LegalDecision {tenant_id: $tenant_id})
        RETURN 
            count(d) as total_decisions,
            sum(CASE WHEN d.legal_decision = 'approved' THEN 1 ELSE 0 END) as approved_count,
            sum(CASE WHEN d.legal_decision = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
            sum(CASE WHEN d.legal_decision = 'modified' THEN 1 ELSE 0 END) as modified_count,
            avg(d.confidence_score) as avg_confidence,
            collect(DISTINCT d.clause_type) as clause_types
        """
        
        result = repository.graph.query(query, {"tenant_id": tenant_id})
        
        if result:
            stats = result[0]
            total = stats.get("total_decisions") or 0
            approved = stats.get("approved_count") or 0
            # avg() is NULL when there are no decisions (round(None) used to 500)
            return {
                "total_decisions": total,
                "decision_breakdown": {
                    "approved": approved,
                    "rejected": stats.get("rejected_count") or 0,
                    "modified": stats.get("modified_count") or 0
                },
                "average_confidence": round(stats.get("avg_confidence") or 0.0, 2),
                "active_clause_types": stats.get("clause_types") or [],
                "approval_rate": round(approved / max(total, 1) * 100, 1)
            }
        else:
            return {
                "total_decisions": 0,
                "decision_breakdown": {"approved": 0, "rejected": 0, "modified": 0},
                "average_confidence": 0.0,
                "active_clause_types": [],
                "approval_rate": 0.0
            }
        
    except Exception as e:
        logger.error(f"Failed to get feedback analytics: {e}")
        raise HTTPException(status_code=500, detail=f"Analytics failed: {str(e)}")

@router.post("/bulk-feedback", dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def submit_bulk_feedback(decisions: List[LegalDecisionRequest], tenant_id: str = Depends(get_current_tenant)):
    """Submit multiple legal decisions at once"""
    try:
        collector = FeedbackCollector()
        decision_ids = []
        
        for request in decisions:
            decision = LegalDecision(
                decision_id=str(uuid.uuid4()),
                contract_id=request.contract_id,
                clause_id=request.clause_id,
                clause_type=request.clause_type,
                original_analysis=request.original_analysis,
                legal_decision=request.legal_decision,
                legal_feedback=request.legal_feedback,
                risk_assessment_override=request.risk_assessment_override,
                confidence_score=request.confidence_score or 0.0,
                decision_timestamp=datetime.now(),
                tenant_id=tenant_id
            )
            
            collector.collect_decision(decision)
            decision_ids.append(decision.decision_id)
        
        return {
            "status": "success",
            "decisions_processed": len(decision_ids),
            "decision_ids": decision_ids
        }
        
    except Exception as e:
        logger.error(f"Failed to submit bulk feedback: {e}")
        raise HTTPException(status_code=500, detail=f"Bulk feedback failed: {str(e)}")