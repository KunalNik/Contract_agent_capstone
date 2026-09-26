from typing import Any, Dict, List, Optional, TypedDict

from backend.domain.value_objects import ProcessingResult, ContractData


class _RequiredPDFState(TypedDict):
    file_path: str
    tenant_id: str
    extracted_text: Optional[str]
    contract_data: Optional[ContractData]
    processing_result: Optional[ProcessingResult]
    messages: list


class PDFProcessingState(_RequiredPDFState, total=False):
    # LangGraph drops keys that are not declared here, so every value a node
    # returns must be listed (sections/clauses were silently lost before).
    filename: str
    content_hash: str
    sections: List[Dict[str, Any]]
    clauses: List[Dict[str, Any]]
    cuad_classifications: List[Dict[str, Any]]
