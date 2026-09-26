from langchain.tools import BaseTool
from typing import Dict, List, Any
import json
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class DeviationDetectorTool(BaseTool):
    """Detect deviations from standard contract patterns - extends existing tool pattern"""
    
    name: str = "deviation_detector"
    description: str = "Detect deviations from company standard contract clauses"
    
    def _run(self, clauses_json: str) -> str:
        """Analyze clauses for deviations from company standards"""
        try:
            clauses = json.loads(clauses_json)
            deviations = []
            
            for clause in clauses:
                clause_type = clause.get("clause_type", "")
                content = clause.get("content", "")
                
                # Check for common deviations
                deviation = self._check_clause_deviation(clause_type, content)
                if deviation:
                    deviations.append({
                        "clause_type": clause_type,
                        "deviation_type": deviation["type"],
                        "severity": deviation["severity"],
                        "issue": deviation["issue"],
                        "suggested_fix": deviation["fix"],
                        "clause_content": content[:200] + "..." if len(content) > 200 else content
                    })
            
            return json.dumps(deviations)
            
        except Exception as e:
            logger.error(f"Deviation detection failed: {e}")
            return json.dumps([])
    
    def _check_clause_deviation(self, clause_type: str, content: str) -> Dict[str, Any]:
        """Check specific clause for deviations"""
        content_lower = content.lower()
        
        # Payment clause deviations
        if clause_type.lower() in ["payment", "payment terms"]:
            if "net 60" in content_lower or "net 90" in content_lower:
                return {
                    "type": "extended_payment_terms",
                    "severity": "MEDIUM",
                    "issue": "Payment terms exceed company standard of Net 30",
                    "fix": "Negotiate payment terms to Net 30 days"
                }
        
        # Liability clause deviations
        if clause_type.lower() in ["liability", "limitation of liability"]:
            if "unlimited liability" in content_lower or "no limitation" in content_lower:
                return {
                    "type": "unlimited_liability",
                    "severity": "CRITICAL",
                    "issue": "Clause allows unlimited liability exposure",
                    "fix": "Add liability cap equal to contract value"
                }
        
        # IP clause deviations
        if clause_type.lower() in ["intellectual property", "ip ownership"]:
            if "work for hire" in content_lower and "customer" in content_lower:
                return {
                    "type": "ip_ownership_transfer",
                    "severity": "HIGH",
                    "issue": "IP ownership transfers to customer",
                    "fix": "Retain IP ownership or negotiate licensing terms"
                }
        
        # Termination clause deviations
        if clause_type.lower() in ["termination", "termination for convenience"]:
            if "no termination" in content_lower or "irrevocable" in content_lower:
                return {
                    "type": "no_termination_rights",
                    "severity": "HIGH",
                    "issue": "Contract lacks termination for convenience",
                    "fix": "Add 30-day termination for convenience clause"
                }
        
        return None

class JurisdictionAdapterTool(BaseTool):
    """Detect contract jurisdiction and adapt analysis - extends existing tool pattern"""
    
    name: str = "jurisdiction_adapter"
    description: str = "Detect contract jurisdiction and adapt rule analysis"
    
    def _run(self, contract_text: str) -> str:
        """Detect jurisdiction and return adapted rules"""
        try:
            jurisdiction = self._detect_jurisdiction(contract_text)
            adapted_rules = self._get_jurisdiction_rules(jurisdiction)
            
            return json.dumps({
                "jurisdiction": jurisdiction,
                "adapted_rules": adapted_rules,
                "compliance_requirements": self._get_compliance_requirements(jurisdiction)
            })
            
        except Exception as e:
            logger.error(f"Jurisdiction adaptation failed: {e}")
            return json.dumps({"jurisdiction": "unknown", "adapted_rules": {}, "compliance_requirements": []})
    
    def _detect_jurisdiction(self, contract_text: str) -> str:
        """Simple jurisdiction detection based on text patterns"""
        text_lower = contract_text.lower()
        
        # EU/GDPR indicators
        if any(term in text_lower for term in ["gdpr", "european union", "eu regulation", "data protection regulation"]):
            return "EU"
        
        # US indicators
        if any(term in text_lower for term in ["delaware law", "new york law", "california law", "governed by the laws of"]):
            return "US"
        
        # UK indicators
        if any(term in text_lower for term in ["english law", "uk law", "courts of england"]):
            return "UK"
        
        return "unknown"
    
    def _get_jurisdiction_rules(self, jurisdiction: str) -> Dict[str, Any]:
        """Get jurisdiction-specific rules"""
        rules = {
            "EU": {
                "data_protection": {"gdpr_compliance": True, "consent_required": True},
                "privacy_rights": {"right_to_deletion": True, "data_portability": True},
                "liability_caps": {"unlimited_liability_restricted": True}
            },
            "US": {
                "data_protection": {"state_privacy_laws": True, "ccpa_compliance": True},
                "liability_caps": {"punitive_damages_allowed": True},
                "employment": {"at_will_employment": True}
            },
            "UK": {
                "data_protection": {"uk_gdpr_compliance": True},
                "contract_law": {"unfair_terms_act": True},
                "liability_caps": {"ucta_compliance": True}
            }
        }
        
        return rules.get(jurisdiction, {})
    
    def _get_compliance_requirements(self, jurisdiction: str) -> List[str]:
        """Get compliance requirements for jurisdiction"""
        requirements = {
            "EU": [
                "GDPR compliance required for personal data processing",
                "Right to deletion must be honored",
                "Data processing basis must be specified"
            ],
            "US": [
                "State privacy laws may apply (CCPA, CPRA)",
                "Industry-specific regulations may apply",
                "Punitive damages may be available"
            ],
            "UK": [
                "UK GDPR compliance required",
                "Unfair Contract Terms Act applies",
                "Consumer rights may apply"
            ]
        }
        
        return requirements.get(jurisdiction, [])

class PrecedentMatcherTool(BaseTool):
    """Find similar contract precedents - extends existing tool pattern"""
    
    name: str = "precedent_matcher"
    description: str = "Find similar contract clauses from precedent database"
    
    def _run(self, clauses_json: str) -> str:
        """Find precedent matches for clauses"""
        try:
            clauses = json.loads(clauses_json)
            matches = []
            
            for clause in clauses:
                precedents = self._find_similar_clauses(clause)
                if precedents:
                    matches.append({
                        "clause": clause,
                        "precedent_count": len(precedents),
                        "approval_rate": self._calculate_approval_rate(precedents),
                        "risk_patterns": self._identify_risk_patterns(precedents),
                        "recommendations": self._generate_recommendations(precedents),
                        "data_source": "illustrative_baseline"
                    })
            
            return json.dumps(matches)
            
        except Exception as e:
            logger.error(f"Precedent matching failed: {e}")
            return json.dumps([])
    
    def _find_similar_clauses(self, clause: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Find similar clauses (simplified for Phase 1)"""
        clause_type = clause.get("clause_type", "").lower()
        # "Payment Terms" / "Limitation of Liability" -> baseline keys
        clause_type = "payment" if "payment" in clause_type else "liability" if "liabilit" in clause_type else clause_type
        
        # Mock precedent data for Phase 1
        mock_precedents = {
            "payment": [
                {"approved": True, "risk_level": "LOW", "terms": "Net 30"},
                {"approved": False, "risk_level": "HIGH", "terms": "Net 90"},
                {"approved": True, "risk_level": "MEDIUM", "terms": "Net 45"}
            ],
            "liability": [
                {"approved": True, "risk_level": "LOW", "terms": "Capped at contract value"},
                {"approved": False, "risk_level": "CRITICAL", "terms": "Unlimited liability"},
                {"approved": True, "risk_level": "MEDIUM", "terms": "Capped at $1M"}
            ]
        }
        
        return mock_precedents.get(clause_type, [])
    
    def _calculate_approval_rate(self, precedents: List[Dict[str, Any]]) -> float:
        """Calculate approval rate from precedents"""
        if not precedents:
            return 0.0
        
        approved = sum(1 for p in precedents if p.get("approved", False))
        return approved / len(precedents)
    
    def _identify_risk_patterns(self, precedents: List[Dict[str, Any]]) -> List[str]:
        """Identify risk patterns from precedents"""
        patterns = []
        
        high_risk_count = sum(1 for p in precedents if p.get("risk_level") in ["HIGH", "CRITICAL"])
        if high_risk_count > len(precedents) * 0.3:
            patterns.append("High risk pattern detected in similar clauses")
        
        low_approval = sum(1 for p in precedents if not p.get("approved", True))
        if low_approval > len(precedents) * 0.5:
            patterns.append("Low approval rate for similar terms")
        
        return patterns
    
    def _generate_recommendations(self, precedents: List[Dict[str, Any]]) -> List[str]:
        """Generate recommendations based on precedents"""
        recommendations = []
        
        approved_precedents = [p for p in precedents if p.get("approved", False)]
        if approved_precedents:
            recommendations.append("Consider terms similar to previously approved contracts")
        
        high_risk_precedents = [p for p in precedents if p.get("risk_level") in ["HIGH", "CRITICAL"]]
        if high_risk_precedents:
            recommendations.append("Review high-risk terms carefully before approval")
        
        return recommendations