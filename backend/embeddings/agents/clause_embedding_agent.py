from typing import Dict, Any, List
import re
from . import EmbeddingAgent, EmbeddingResult
from backend.embeddings.strategies.factory import EmbeddingFactory
from backend.embeddings.strategies import EmbeddingType

class ClauseEmbeddingAgent(EmbeddingAgent):
    """Agent for extracting and embedding contract clauses"""
    
    def __init__(self):
        self.factory = EmbeddingFactory()
        self.strategy = self.factory.create_strategy(EmbeddingType.CLAUSE)
        self.cuad_patterns = self._build_clause_patterns()
    
    def process(self, content: str, metadata: Dict[str, Any] = None) -> List[EmbeddingResult]:
        """Extract clauses and create embeddings"""
        results = []
        
        # Extract clauses using pattern matching
        for clause_type, patterns in self.cuad_patterns.items():
            clauses = self._extract_clauses(content, patterns, clause_type)
            
            for clause in clauses:
                clause_embedding = self.strategy.generate_embedding(
                    clause["content"], 
                    {"clause_type": clause_type}
                )
                
                results.append(EmbeddingResult(
                    embedding=clause_embedding,
                    metadata={
                        **(metadata or {}),
                        "clause_type": clause_type,
                        "confidence": clause["confidence"],
                        "start_position": clause["start"],
                        "end_position": clause["end"]
                    },
                    content=clause["content"],
                    embedding_type="clause"
                ))
        
        return results
    
    def _build_clause_patterns(self) -> Dict[str, List[str]]:
        """Build regex patterns for CUAD clause types"""
        return {
            "Termination For Convenience": [
                r"terminat.*convenience",
                r"end.*agreement.*reason",
                r"cancel.*without cause"
            ],
            "Governing Law": [
                r"governed by.*law",
                r"jurisdiction.*court",
                r"applicable law"
            ],
            "Non-Compete": [
                r"non.?compet",
                r"not.*compet.*business",
                r"restrict.*competition"
            ],
            "IP Ownership Assignment": [
                r"intellectual property.*assign",
                r"ownership.*ip",
                r"patent.*copyright.*assign"
            ],
            "Cap On Liability": [
                r"liability.*limited",
                r"damages.*exceed",
                r"maximum.*liability"
            ],
            "Payment Terms": [
                r"payment.*due",
                r"invoice.*pay",
                r"fee.*amount",
                # "pay all invoices", "paid against invoices": pay before invoice
                r"\bpa(?:y|id)\b.*\binvoices?\b",
                # "invoice shall be paid": "paid" doesn't contain "pay"
                r"\binvoices?\b.*\bpaid\b",
                r"\bpayment terms\b"
            ]
        }
    
    def _extract_clauses(self, content: str, patterns: List[str], clause_type: str) -> List[Dict[str, Any]]:
        """Extract clauses matching patterns"""
        clauses = []
        
        for pattern in patterns:
            matches = re.finditer(pattern, content, re.IGNORECASE)
            
            for match in matches:
                # Extract surrounding context (sentence or paragraph)
                start = max(0, content.rfind('.', 0, match.start()) + 1)
                end = content.find('.', match.end())
                if end == -1:
                    end = len(content)
                
                clause_content = content[start:end].strip()
                
                if len(clause_content) > 20:  # Only substantial clauses
                    clauses.append({
                        "content": clause_content,
                        "start": start,
                        "end": end,
                        "confidence": 0.8  # Basic confidence score
                    })
        
        return clauses