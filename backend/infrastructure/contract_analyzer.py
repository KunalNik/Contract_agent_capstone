from backend.domain.entities import IContractAnalyzer
from backend.shared.utils.contract_search_tool import CONTRACT_TYPES
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class ContractParty(BaseModel):
    name: str
    role: str = "Unknown"

class ContractAnalysis(BaseModel):
    is_contract: bool = Field(description="Whether this is a legal contract")
    confidence_score: float = Field(description="Confidence 0.0-1.0")
    contract_type: str = Field(description="Type of contract")
    summary: str = Field(description="Brief contract summary")
    parties: List[ContractParty] = Field(default_factory=list)
    effective_date: Optional[str] = None
    end_date: Optional[str] = None
    total_amount: Optional[float] = None
    governing_law: Optional[str] = None
    key_terms: List[str] = Field(default_factory=list)

class LLMContractAnalyzer(IContractAnalyzer):
    """Contract analysis using LLM - reuses existing infrastructure"""
    
    def __init__(self, llm):
        self.llm = llm
        self.parser = PydanticOutputParser(pydantic_object=ContractAnalysis)
    
    def analyze_contract(self, text: str) -> Dict[str, Any]:
        """Analyze contract text and extract structured data"""
        if self.llm is None:
            raise ValueError("No LLM configured for contract analysis (set GOOGLE_API_KEY)")
        analysis_text = text[:8000] if len(text) > 8000 else text

        prompt = f"""Analyze this document:

{analysis_text}

{self.parser.get_format_instructions()}

confidence_score must be between 0.0 and 1.0. total_amount must be a plain number or null.
Use contract_type from: {CONTRACT_TYPES}"""

        response = self.llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        try:
            return self._normalise(self.parser.parse(content).model_dump())
        except Exception as strict_error:
            # Models often wrap JSON in prose/fences or use 0-100 scores and
            # "$1,000" amounts; normalise instead of failing the whole upload.
            from backend.governance.llm_judge import _extract_json
            try:
                data = _extract_json(content)
            except Exception:
                raise strict_error
            return self._normalise(data)

    @staticmethod
    def _normalise(data: Dict[str, Any]) -> Dict[str, Any]:
        confidence = data.get("confidence_score", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence > 1.0:
            confidence = confidence / 100.0 if confidence <= 100 else 1.0
        amount = data.get("total_amount")
        if isinstance(amount, str):
            try:
                amount = float(amount.replace(",", "").replace("$", "").strip())
            except ValueError:
                amount = None
        parties = []
        for party in data.get("parties") or []:
            if isinstance(party, str):
                parties.append({"name": party, "role": "Unknown"})
            elif isinstance(party, dict) and party.get("name"):
                parties.append({"name": str(party["name"]), "role": str(party.get("role") or "Unknown")})
        key_terms = data.get("key_terms") or []
        return ContractAnalysis(
            is_contract=bool(data.get("is_contract", False)),
            confidence_score=max(0.0, confidence),
            contract_type=str(data.get("contract_type") or "Unknown"),
            summary=str(data.get("summary") or ""),
            parties=parties,
            effective_date=data.get("effective_date"),
            end_date=data.get("end_date"),
            total_amount=amount,
            governing_law=data.get("governing_law"),
            key_terms=[str(k) for k in key_terms] if isinstance(key_terms, list) else [str(key_terms)],
        ).model_dump()
