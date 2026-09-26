import asyncio

from backend.domain.entities import DocumentProcessingRequest
from backend.application.services.document_processing_service import DocumentProcessingService
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)


class EnhancedDocumentProcessingService(DocumentProcessingService):
    """
    Enhanced document processing service with multi-level embeddings.

    Same pipeline as the basic service, but embeddings are generated before
    the response is returned so the caller gets their status.
    (Previously this ran the async LangGraph agent with sync .invoke(), which
    always failed, and dropped the tenant.)
    """

    async def process_pdf_with_embeddings(self, request: DocumentProcessingRequest) -> dict:
        try:
            logger.info(f"Starting enhanced PDF processing for: {request.filename}")
            model_name = (request.processing_options or {}).get("model", "gemini-2.5-flash")
            pdf_agent = self.pdf_agent_factory.create_agent(self._get_llm_for_model(model_name))

            result, extracted_text = await self._process_with_agent(pdf_agent, request)
            embedding_success = False
            if result.get("contract_id"):
                embedding_success = await asyncio.to_thread(
                    self.embedding_pipeline.run,
                    result["contract_id"], extracted_text, request.filename, request.tenant_id or "default-tenant",
                )
            result["enhanced_embeddings"] = embedding_success
            if result.get("contract_id"):
                result["final_result"] = f"Processing {result['status']} with enhanced embeddings"
            return result
        finally:
            self._cleanup_file(request.file_path)


class EnhancedDocumentServiceFactory:
    """Factory for creating enhanced document processing services"""

    @staticmethod
    def create_service(agent_manager):
        """Create enhanced document processing service with dependencies"""
        return EnhancedDocumentProcessingService(agent_manager)
