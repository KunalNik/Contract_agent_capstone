from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import json
import logging
from backend.infrastructure.contract_repository import Neo4jContractRepository

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

@dataclass
class LegalDecision:
    """Legal team decision on contract analysis"""
    decision_id: str
    contract_id: str
    clause_id: str
    clause_type: str
    original_analysis: Dict[str, Any]
    legal_decision: str  # "approved", "rejected", "modified"
    legal_feedback: str
    risk_assessment_override: Optional[str] = None
    confidence_score: float = 0.0
    decision_timestamp: datetime = None
    tenant_id: str = "default-tenant"
    
    def __post_init__(self):
        if self.decision_timestamp is None:
            self.decision_timestamp = datetime.now()

@dataclass
class FeedbackPattern:
    """Pattern learned from legal team feedback"""
    pattern_id: str
    pattern_type: str  # "deviation", "risk", "approval"
    conditions: Dict[str, Any]
    learned_outcome: str
    confidence: float
    usage_count: int = 0
    success_rate: float = 0.0

class FeedbackCollector:
    """Collect and store legal team decisions"""
    
    def __init__(self):
        self.repository = Neo4jContractRepository()
    
    def collect_decision(self, decision: LegalDecision) -> None:
        """Store legal team decision.

        Raises LookupError if the contract does not exist for the tenant, and
        re-raises write failures (errors used to be swallowed while the API
        reported success).
        """
        try:
            query = """
            MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
            MERGE (d:LegalDecision {decision_id: $decision_id})
            SET d.tenant_id = $tenant_id,
                d.contract_id = $contract_id,
                d.clause_id = $clause_id,
                d.clause_type = $clause_type,
                d.original_analysis = $original_analysis,
                d.legal_decision = $legal_decision,
                d.legal_feedback = $legal_feedback,
                d.risk_assessment_override = $risk_assessment_override,
                d.confidence_score = $confidence_score,
                d.decision_timestamp = $decision_timestamp
            MERGE (c)-[:HAS_DECISION]->(d)
            RETURN d.decision_id AS decision_id
            """
            
            rows = self.repository.graph.query(query, {
                "tenant_id": decision.tenant_id,
                "decision_id": decision.decision_id,
                "contract_id": decision.contract_id,
                "clause_id": decision.clause_id,
                "clause_type": decision.clause_type,
                "original_analysis": json.dumps(decision.original_analysis),
                "legal_decision": decision.legal_decision,
                "legal_feedback": decision.legal_feedback,
                "risk_assessment_override": decision.risk_assessment_override,
                "confidence_score": decision.confidence_score,
                "decision_timestamp": decision.decision_timestamp.isoformat()
            })
            if not rows:
                raise LookupError(f"Contract {decision.contract_id} not found")
            
            logger.info(f"Stored legal decision: {decision.decision_id}")
            
        except LookupError:
            raise
        except Exception as e:
            logger.error(f"Failed to store legal decision: {e}")
            raise
    
    def get_decisions_by_clause_type(self, clause_type: str, limit: int = 50,
                                     tenant_id: str = "default-tenant") -> List[LegalDecision]:
        """Get legal decisions for specific clause type (one tenant's decisions only)"""
        try:
            query = """
            MATCH (d:LegalDecision {tenant_id: $tenant_id})
            WHERE d.clause_type = $clause_type
            RETURN d
            ORDER BY d.decision_timestamp DESC
            LIMIT $limit
            """
            
            results = self.repository.graph.query(query, {
                "clause_type": clause_type,
                "limit": limit,
                "tenant_id": tenant_id
            })
            
            decisions = []
            for result in results:
                d = result["d"]
                decisions.append(LegalDecision(
                    decision_id=d.get("decision_id"),
                    contract_id=d.get("contract_id"),
                    clause_id=d.get("clause_id"),
                    clause_type=d.get("clause_type"),
                    original_analysis=json.loads(d.get("original_analysis") or "{}"),
                    legal_decision=d.get("legal_decision"),
                    legal_feedback=d.get("legal_feedback"),
                    risk_assessment_override=d.get("risk_assessment_override"),
                    confidence_score=d.get("confidence_score", 0.0),
                    decision_timestamp=datetime.fromisoformat(d.get("decision_timestamp")) if d.get("decision_timestamp") else None,
                    tenant_id=d.get("tenant_id") or tenant_id
                ))
            
            return decisions
            
        except Exception as e:
            logger.error(f"Failed to get decisions for clause type {clause_type}: {e}")
            return []

class PatternLearner:
    """Learn patterns from legal team feedback"""
    
    def __init__(self, tenant_id: Optional[str] = None):
        from backend.shared.utils.request_context import current_tenant
        self.tenant_id = tenant_id or current_tenant()
        self.collector = FeedbackCollector()
        self.learned_patterns: List[FeedbackPattern] = []
    
    def learn_from_decisions(self, clause_type: str) -> List[FeedbackPattern]:
        """Learn patterns from legal decisions"""
        decisions = self.collector.get_decisions_by_clause_type(clause_type, tenant_id=self.tenant_id)
        
        if len(decisions) < 5:  # Need minimum decisions to learn patterns
            return []
        
        patterns = []
        
        # Learn approval patterns
        approved_decisions = [d for d in decisions if d.legal_decision == "approved"]
        if approved_decisions:
            approval_pattern = self._extract_approval_pattern(approved_decisions, clause_type)
            if approval_pattern:
                patterns.append(approval_pattern)
        
        # Learn rejection patterns
        rejected_decisions = [d for d in decisions if d.legal_decision == "rejected"]
        if rejected_decisions:
            rejection_pattern = self._extract_rejection_pattern(rejected_decisions, clause_type)
            if rejection_pattern:
                patterns.append(rejection_pattern)
        
        # Learn risk assessment patterns
        override_decisions = [d for d in decisions if d.risk_assessment_override]
        if override_decisions:
            risk_pattern = self._extract_risk_pattern(override_decisions, clause_type)
            if risk_pattern:
                patterns.append(risk_pattern)
        
        self.learned_patterns.extend(patterns)
        return patterns
    
    def _extract_approval_pattern(self, decisions: List[LegalDecision], clause_type: str) -> Optional[FeedbackPattern]:
        """Extract common patterns from approved decisions"""
        if len(decisions) < 3:
            return None
        
        # Analyze common characteristics of approved clauses
        common_keywords = self._find_common_keywords([d.original_analysis for d in decisions])
        common_risk_levels = self._find_common_risk_levels([d.original_analysis for d in decisions])
        
        if common_keywords or common_risk_levels:
            return FeedbackPattern(
                pattern_id=f"approval_{clause_type}_{datetime.now().strftime('%Y%m%d')}",
                pattern_type="approval",
                conditions={
                    "clause_type": clause_type,
                    "common_keywords": common_keywords,
                    "acceptable_risk_levels": common_risk_levels
                },
                learned_outcome="likely_approved",
                confidence=min(1.0, len(decisions) / 10.0),  # Confidence based on sample size (capped)
                usage_count=0,
                success_rate=0.0
            )
        
        return None
    
    def _extract_rejection_pattern(self, decisions: List[LegalDecision], clause_type: str) -> Optional[FeedbackPattern]:
        """Extract common patterns from rejected decisions"""
        if len(decisions) < 3:
            return None
        
        # Analyze common reasons for rejection
        rejection_keywords = []
        for decision in decisions:
            feedback_words = decision.legal_feedback.lower().split()
            rejection_keywords.extend(feedback_words)
        
        # Find most common rejection reasons
        keyword_counts = {}
        for keyword in rejection_keywords:
            if len(keyword) > 3:  # Filter short words
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
        
        common_rejection_reasons = [k for k, v in keyword_counts.items() if v >= 2]
        
        if common_rejection_reasons:
            return FeedbackPattern(
                pattern_id=f"rejection_{clause_type}_{datetime.now().strftime('%Y%m%d')}",
                pattern_type="rejection",
                conditions={
                    "clause_type": clause_type,
                    "rejection_indicators": common_rejection_reasons
                },
                learned_outcome="likely_rejected",
                confidence=min(1.0, len(decisions) / 10.0),
                usage_count=0,
                success_rate=0.0
            )
        
        return None
    
    def _extract_risk_pattern(self, decisions: List[LegalDecision], clause_type: str) -> Optional[FeedbackPattern]:
        """Extract risk assessment override patterns"""
        if len(decisions) < 2:
            return None
        
        # Analyze risk assessment overrides
        override_patterns = {}
        for decision in decisions:
            original_risk = decision.original_analysis.get("risk_level", "UNKNOWN")
            override_risk = decision.risk_assessment_override
            
            pattern_key = f"{original_risk}_to_{override_risk}"
            override_patterns[pattern_key] = override_patterns.get(pattern_key, 0) + 1
        
        # Find most common override pattern
        most_common_override = max(override_patterns.items(), key=lambda x: x[1])
        
        if most_common_override[1] >= 2:  # At least 2 occurrences
            return FeedbackPattern(
                pattern_id=f"risk_override_{clause_type}_{datetime.now().strftime('%Y%m%d')}",
                pattern_type="risk_override",
                conditions={
                    "clause_type": clause_type,
                    "override_pattern": most_common_override[0]
                },
                learned_outcome=f"risk_adjustment_{most_common_override[0]}",
                confidence=most_common_override[1] / len(decisions),
                usage_count=0,
                success_rate=0.0
            )
        
        return None
    
    def _find_common_keywords(self, analyses: List[Dict[str, Any]]) -> List[str]:
        """Find common keywords across analyses"""
        all_keywords = []
        for analysis in analyses:
            content = analysis.get("content", "").lower()
            all_keywords.extend(content.split())
        
        # Count keyword frequency
        keyword_counts = {}
        for keyword in all_keywords:
            if len(keyword) > 4:  # Filter short words
                keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1
        
        # Return keywords that appear in at least 50% of analyses
        threshold = len(analyses) * 0.5
        return [k for k, v in keyword_counts.items() if v >= threshold]
    
    def _find_common_risk_levels(self, analyses: List[Dict[str, Any]]) -> List[str]:
        """Find common risk levels in approved analyses"""
        risk_levels = [analysis.get("risk_level", "UNKNOWN") for analysis in analyses]
        risk_counts = {}
        for level in risk_levels:
            risk_counts[level] = risk_counts.get(level, 0) + 1
        
        # Return risk levels that appear in at least 30% of analyses
        threshold = len(analyses) * 0.3
        return [k for k, v in risk_counts.items() if v >= threshold]

class AdaptiveAnalyzer:
    """Apply learned patterns to improve analysis"""
    
    def __init__(self, tenant_id: Optional[str] = None):
        self.pattern_learner = PatternLearner(tenant_id)
        self.active_patterns: Dict[str, List[FeedbackPattern]] = {}
    
    def load_patterns_for_clause_type(self, clause_type: str) -> None:
        """Load learned patterns for specific clause type"""
        patterns = self.pattern_learner.learn_from_decisions(clause_type)
        self.active_patterns[clause_type] = patterns
        logger.info(f"Loaded {len(patterns)} patterns for clause type: {clause_type}")
    
    def enhance_analysis(self, clause: Dict[str, Any], original_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Enhance analysis using learned patterns"""
        clause_type = clause.get("clause_type", "")
        
        # Load patterns if not already loaded
        if clause_type not in self.active_patterns:
            self.load_patterns_for_clause_type(clause_type)
        
        patterns = self.active_patterns.get(clause_type, [])
        enhanced_analysis = dict(original_analysis)
        
        # Apply learned patterns
        for pattern in patterns:
            enhancement = self._apply_pattern(clause, original_analysis, pattern)
            if enhancement:
                enhanced_analysis.update(enhancement)
        
        return enhanced_analysis
    
    def _apply_pattern(self, clause: Dict[str, Any], analysis: Dict[str, Any], pattern: FeedbackPattern) -> Optional[Dict[str, Any]]:
        """Apply a specific learned pattern"""
        try:
            if pattern.pattern_type == "approval":
                return self._apply_approval_pattern(clause, analysis, pattern)
            elif pattern.pattern_type == "rejection":
                return self._apply_rejection_pattern(clause, analysis, pattern)
            elif pattern.pattern_type == "risk_override":
                return self._apply_risk_pattern(clause, analysis, pattern)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to apply pattern {pattern.pattern_id}: {e}")
            return None
    
    def _apply_approval_pattern(self, clause: Dict[str, Any], analysis: Dict[str, Any], pattern: FeedbackPattern) -> Optional[Dict[str, Any]]:
        """Apply approval pattern"""
        conditions = pattern.conditions
        content = clause.get("content", "").lower()
        
        # Check if clause matches approval pattern
        common_keywords = conditions.get("common_keywords", [])
        if not common_keywords:
            return None  # 0 >= 0 used to flag every clause as "likely approved"
        keyword_matches = sum(1 for keyword in common_keywords if keyword in content)
        
        if keyword_matches >= len(common_keywords) * 0.5:  # 50% keyword match
            return {
                "learned_approval_likelihood": "high",
                "pattern_confidence": pattern.confidence,
                "matching_keywords": [k for k in common_keywords if k in content]
            }
        
        return None
    
    def _apply_rejection_pattern(self, clause: Dict[str, Any], analysis: Dict[str, Any], pattern: FeedbackPattern) -> Optional[Dict[str, Any]]:
        """Apply rejection pattern"""
        conditions = pattern.conditions
        content = clause.get("content", "").lower()
        
        # Check for rejection indicators
        rejection_indicators = conditions.get("rejection_indicators", [])
        indicator_matches = [indicator for indicator in rejection_indicators if indicator in content]
        
        if indicator_matches:
            return {
                "learned_rejection_risk": "high",
                "rejection_indicators_found": indicator_matches,
                "pattern_confidence": pattern.confidence
            }
        
        return None
    
    def _apply_risk_pattern(self, clause: Dict[str, Any], analysis: Dict[str, Any], pattern: FeedbackPattern) -> Optional[Dict[str, Any]]:
        """Apply risk override pattern"""
        conditions = pattern.conditions
        current_risk = analysis.get("risk_level", "UNKNOWN")
        
        override_pattern = conditions.get("override_pattern", "")
        if override_pattern.startswith(f"{current_risk}_to_"):
            suggested_risk = override_pattern.split("_to_")[1]
            return {
                "learned_risk_adjustment": suggested_risk,
                "original_risk": current_risk,
                "pattern_confidence": pattern.confidence
            }
        
        return None