"""
Document Processor Factory
Factory Pattern for creating different document processors
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
from backend.agents.pdf_processing_agent import PDFAgentFactory
from backend.agents.enhanced_pdf_processing_agent import EnhancedPDFAgentFactory
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

class IDocumentProcessor(ABC):
    """Interface for document processors"""
    
    @abstractmethod
    async def process_document(self, file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """Process document and return results"""
        pass

def _summarise(result: Dict[str, Any], processor_type: str) -> Dict[str, Any]:
    """Turn the final graph state into an API result.

    processing_result is a ProcessingResult dataclass (the old code called
    .get() on it and reported "success" even when storage failed).
    """
    processing = result.get("processing_result")
    status = getattr(getattr(processing, "status", None), "value", "error")
    return {
        "status": status,
        "processor_type": processor_type,
        "contract_id": getattr(processing, "contract_id", None),
        "message": getattr(processing, "message", "") or "",
        "error": getattr(processing, "error", None),
        "sections_extracted": len(result.get("sections") or []),
        "clauses_extracted": len(result.get("clauses") or []),
        "cuad_classifications": len(result.get("cuad_classifications") or []),
    }


class _GraphDocumentProcessor(IDocumentProcessor):
    processor_type = "basic"

    def __init__(self, llm):
        self.llm = llm
        self.agent = self._create_agent(llm)

    def _create_agent(self, llm):
        return PDFAgentFactory.create_agent(llm)

    async def process_document(self, file_path: str, options: Dict[str, Any]) -> Dict[str, Any]:
        try:
            state = {
                "file_path": file_path,
                "tenant_id": options.get("tenant_id", "default-tenant"),
                "filename": options.get("filename", ""),
                "content_hash": options.get("content_hash", ""),
                "extracted_text": None,
                "contract_data": None,
                "processing_result": None,
                "messages": [],
            }
            result = await self.agent.ainvoke(state)
            return _summarise(result, self.processor_type)
        except Exception as e:
            logger.error(f"{self.processor_type} processing failed: {e}", exc_info=True)
            return {"status": "error", "processor_type": self.processor_type, "error": str(e),
                    "contract_id": None, "sections_extracted": 0, "clauses_extracted": 0,
                    "cuad_classifications": 0}


class BasicDocumentProcessor(_GraphDocumentProcessor):
    """Basic document processor - existing functionality"""
    processor_type = "basic"


class EnhancedDocumentProcessor(_GraphDocumentProcessor):
    """Enhanced document processor with sections"""
    processor_type = "enhanced"

    def _create_agent(self, llm):
        return EnhancedPDFAgentFactory.create_agent(llm, "enhanced")


class FullDocumentProcessor(EnhancedDocumentProcessor):
    """Full document processor with sections + clauses + CUAD"""
    processor_type = "full"


class DocumentProcessorFactory:
    """Factory for creating document processors"""
    
    @staticmethod
    def create_processor(processor_type: str, llm) -> IDocumentProcessor:
        """Create document processor based on type"""
        
        if processor_type == "basic":
            return BasicDocumentProcessor(llm)
        elif processor_type == "enhanced":
            return EnhancedDocumentProcessor(llm)
        elif processor_type == "full":
            return FullDocumentProcessor(llm)
        else:
            raise ValueError(f"Unknown processor type: {processor_type}")
    
    @staticmethod
    def get_available_types() -> list:
        """Get available processor types"""
        return ["basic", "enhanced", "full"]
    
    @staticmethod
    def get_processor_capabilities(processor_type: str) -> Dict[str, bool]:
        """Get capabilities of processor type"""
        capabilities = {
            "basic": {
                "contract_analysis": True,
                "section_extraction": False,
                "clause_extraction": False,
                "cuad_classification": False,
                "embeddings": False
            },
            "enhanced": {
                "contract_analysis": True,
                "section_extraction": True,
                "clause_extraction": False,
                "cuad_classification": False,
                "embeddings": True
            },
            "full": {
                "contract_analysis": True,
                "section_extraction": True,
                "clause_extraction": True,
                "cuad_classification": True,
                "embeddings": True
            }
        }
        
        return capabilities.get(processor_type, {})