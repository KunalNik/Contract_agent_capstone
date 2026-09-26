"""
CUAD Classifier Agent
Template Method + Decorator Pattern for 41 CUAD clause types
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import re
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

# 41 CUAD Clause Types
CUAD_CLAUSE_TYPES = [
    "Document Name", "Parties", "Agreement Date", "Effective Date", "Expiration Date",
    "Renewal Term", "Notice Period To Terminate Renewal", "Governing Law", "Most Favored Nation",
    "Non-Compete", "Exclusivity", "No-Solicit Of Customers", "Competitive Restriction Exception",
    "No-Solicit Of Employees", "Non-Disparagement", "Termination For Convenience", "Rofr/Rofo/Rofn",
    "Change Of Control", "Anti-Assignment", "Revenue/Customer Sharing", "Price Restrictions",
    "Minimum Commitment", "Volume Restriction", "Ip Ownership Assignment", "Joint Ip Ownership",
    "License Grant", "Non-Transferable License", "Affiliate License-Licensor", "Affiliate License-Licensee",
    "Unlimited/All-You-Can-Eat-License", "Irrevocable Or Perpetual License", "Source Code Escrow",
    "Post-Termination Services", "Audit Rights", "Uncapped Liability", "Cap On Liability",
    "Liquidated Damages", "Warranty Duration", "Insurance", "Covenant Not To Sue",
    "Third Party Beneficiary", "Irrevocable Or Perpetual License"
]

@dataclass
class CUADClassification:
    """CUAD classification result"""
    clause_id: str
    cuad_type: str
    confidence: float
    detected_by: str
    reasoning: str = ""

class ICUADClassifier(ABC):
    """Template method interface for CUAD classification"""
    
    @abstractmethod
    def classify_clause(self, clause: Dict[str, Any]) -> List[CUADClassification]:
        """Classify clause into CUAD types"""
        pass

class RegexCUADClassifier(ICUADClassifier):
    """Rule-based CUAD classification using regex patterns"""
    
    def __init__(self):
        self.patterns = self._build_patterns()
    
    def _build_patterns(self) -> Dict[str, List[str]]:
        """Build regex patterns for CUAD types"""
        return {
            "Governing Law": [
                r"governed by.*law",
                r"laws of.*state",
                r"jurisdiction.*court"
            ],
            "Termination For Convenience": [
                r"terminate.*convenience",
                r"terminate.*without cause",
                r"terminate.*any reason"
            ],
            "Non-Compete": [
                r"non.?compete",
                r"not.*compete",
                r"competitive.*restriction"
            ],
            "Exclusivity": [
                r"exclusive",
                r"solely",
                r"exclusively"
            ],
            "Minimum Commitment": [
                r"minimum.*purchase",
                r"minimum.*order",
                r"commitment.*amount"
            ],
            "Cap On Liability": [
                r"liability.*limited",
                r"maximum.*liability",
                r"cap.*liability"
            ],
            "Warranty Duration": [
                r"warranty.*period",
                r"warranty.*duration",
                r"warranted.*days"
            ]
        }
    
    def classify_clause(self, clause: Dict[str, Any]) -> List[CUADClassification]:
        """Classify using regex patterns"""
        content = clause["content"].lower()
        clause_id = clause["clause_id"]
        classifications = []
        
        for cuad_type, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, content, re.IGNORECASE):
                    classification = CUADClassification(
                        clause_id=clause_id,
                        cuad_type=cuad_type,
                        confidence=0.8,
                        detected_by="regex",
                        reasoning=f"Matched pattern: {pattern}"
                    )
                    classifications.append(classification)
                    break  # One match per type
        
        return classifications

class LLMCUADClassifier(ICUADClassifier):
    """LLM-based CUAD classification"""
    
    def __init__(self, llm):
        self.llm = llm
    
    def classify_clause(self, clause: Dict[str, Any]) -> List[CUADClassification]:
        """Classify using LLM analysis"""
        content = clause["content"]
        clause_id = clause["clause_id"]
        
        # Select relevant CUAD types for this clause
        relevant_types = self._select_relevant_types(content)
        if not relevant_types:
            return []  # nothing plausible to ask the model about
        
        prompt = f"""
        Classify this contract clause into CUAD categories:
        
        Clause: {content}
        
        Possible CUAD types: {', '.join(relevant_types)}
        
        Return JSON: [{{"cuad_type": "type", "confidence": 0.0-1.0, "reasoning": "explanation"}}]
        
        Only return matches with confidence > 0.7.
        """
        
        try:
            response = self.llm.invoke(prompt)
            return self._parse_llm_response(response.content, clause_id)
        except Exception as e:
            logger.error(f"LLM CUAD classification failed: {e}")
            return []
    
    def _select_relevant_types(self, content: str) -> List[str]:
        """Select relevant CUAD types based on content keywords"""
        content_lower = content.lower()
        relevant = []
        
        keyword_mapping = {
            "governing": ["Governing Law"],
            "terminate": ["Termination For Convenience"],
            "compete": ["Non-Compete"],
            "exclusive": ["Exclusivity"],
            "minimum": ["Minimum Commitment"],
            "liability": ["Cap On Liability", "Uncapped Liability"],
            "warranty": ["Warranty Duration"]
        }
        
        for keyword, types in keyword_mapping.items():
            if keyword in content_lower:
                relevant.extend(types)
        
        return relevant[:5]  # Limit to 5 most relevant
    
    def _parse_llm_response(self, response, clause_id: str) -> List[CUADClassification]:
        """Parse the LLM's JSON array into classifications (confidence > 0.7 only)."""
        from backend.governance.llm_judge import _extract_json
        if isinstance(response, list):
            response = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in response)
        text = response.strip()
        try:
            data = _extract_json(text if text.startswith(("{", "`")) else f'{{"c": {text}}}')
        except Exception as e:
            logger.error(f"Could not parse LLM CUAD output: {e}")
            return []
        items = data.get("c") or data.get("classifications") or [] if isinstance(data, dict) else data
        results = []
        for item in items or []:
            try:
                confidence = float(item.get("confidence", 0))
            except (TypeError, ValueError):
                continue
            if item.get("cuad_type") and confidence > 0.7:
                results.append(CUADClassification(clause_id=clause_id, cuad_type=str(item["cuad_type"]),
                                                  confidence=min(confidence, 1.0), detected_by="llm",
                                                  reasoning=str(item.get("reasoning", ""))))
        return results

def cuad_confidence_decorator(func):
    """Decorator to adjust CUAD confidence scores"""
    def wrapper(*args, **kwargs):
        classifications = func(*args, **kwargs)
        
        for classification in classifications:
            # Boost confidence for high-quality matches
            if len(classification.reasoning) > 50:
                classification.confidence = min(classification.confidence + 0.1, 1.0)
            
            # Reduce confidence for short clauses
            if len(args[1]["content"]) < 50:  # args[1] is clause
                classification.confidence *= 0.8
        
        return classifications
    return wrapper

class CUADClassifierAgent:
    """Main CUAD classification agent"""
    
    def __init__(self, llm, strategy: str = "hybrid"):
        self.llm = llm
        self.regex_classifier = RegexCUADClassifier()
        self.llm_classifier = LLMCUADClassifier(llm) if llm else None
        self.strategy = strategy
    
    @cuad_confidence_decorator
    def classify_clause(self, clause: Dict[str, Any]) -> List[CUADClassification]:
        """Classify clause using selected strategy"""
        if self.strategy == "regex":
            return self.regex_classifier.classify_clause(clause)
        elif self.strategy == "llm" and self.llm_classifier:
            return self.llm_classifier.classify_clause(clause)
        elif self.strategy == "hybrid":
            return self._hybrid_classification(clause)
        else:
            return []
    
    def _hybrid_classification(self, clause: Dict[str, Any]) -> List[CUADClassification]:
        """Combine regex and LLM classifications"""
        regex_results = self.regex_classifier.classify_clause(clause)
        
        if regex_results:
            # Use regex if found matches
            return regex_results
        elif self.llm_classifier:
            # Fallback to LLM for complex cases
            return self.llm_classifier.classify_clause(clause)
        else:
            return []
    
    def classify_clauses_batch(self, clauses: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Classify multiple clauses efficiently"""
        classifications = []
        
        for clause in clauses:
            clause_classifications = self.classify_clause(clause)
            
            for classification in clause_classifications:
                classification_dict = {
                    "classification_id": f"{classification.clause_id}_{classification.cuad_type.lower().replace(' ', '_')}",
                    "clause_id": classification.clause_id,
                    "cuad_type": classification.cuad_type,
                    "confidence": classification.confidence,
                    "detected_by": classification.detected_by,
                    "reasoning": classification.reasoning
                }
                classifications.append(classification_dict)
        
        return classifications