import asyncio
import os

from backend.domain.entities import DocumentProcessingRequest
from backend.agents.pdf_processing_agent import PDFAgentFactory
from backend.agents.agent_workflow_tracker import workflow_tracker
from backend.application.services.embedding_pipeline import EmbeddingPipeline
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)


def get_chat_model(llm_manager, model_name: str):
    """Raw chat model from the app's LLMManager (None if no provider is configured)."""
    try:
        return llm_manager.get_chat_model(model_name)
    except (ValueError, AttributeError) as e:
        logger.error(f"No chat model available for '{model_name}': {e}")
        return None


class DocumentProcessingService:
    """
    Application Service for document processing
    Follows Single Responsibility Principle with structured output
    """

    def __init__(self, agent_manager):
        self.agent_manager = agent_manager
        self.pdf_agent_factory = PDFAgentFactory()
        self.embedding_pipeline = EmbeddingPipeline()

    async def process_pdf_upload(self, request: DocumentProcessingRequest, background_tasks=None) -> dict:
        """
        Process uploaded PDF using agent-based workflow with structured output.
        Multi-level embeddings run afterwards (in background_tasks when given).
        """
        try:
            logger.info(f"Starting PDF processing for: {request.filename}")

            if not os.path.exists(request.file_path):
                raise FileNotFoundError(f"File not found: {request.file_path}")

            model_name = (request.processing_options or {}).get("model", "gemini-2.5-flash")
            llm = self._get_llm_for_model(model_name)
            pdf_agent = self.pdf_agent_factory.create_agent(llm)

            result, extracted_text = await self._process_with_agent(pdf_agent, request)

            if result.get("contract_id") and extracted_text:
                args = (result["contract_id"], extracted_text, request.filename, request.tenant_id or "default-tenant")
                if background_tasks is not None:
                    background_tasks.add_task(asyncio.to_thread, self.embedding_pipeline.run, *args)
                else:
                    await asyncio.to_thread(self.embedding_pipeline.run, *args)

            logger.info(f"PDF processing completed for: {request.filename}")
            return result

        finally:
            self._cleanup_file(request.file_path)

    def _get_llm_for_model(self, model_name: str):
        """Get LLM instance from the shared manager (supports every configured model)."""
        return get_chat_model(self.agent_manager, model_name)

    async def _process_with_agent(self, pdf_agent, request: DocumentProcessingRequest):
        """Process document using PDF agent with structured output"""

        workflow_tracker.start_workflow()
        execution = workflow_tracker.start_agent(
            "PDF Processing Agent",
            "Extract text and analyze contract structure from PDF",
            f"PDF file: {request.filename}"
        )

        options = request.processing_options or {}
        initial_state = {
            "file_path": request.file_path,
            "tenant_id": request.tenant_id or "default-tenant",
            "filename": request.filename,
            "content_hash": options.get("content_hash", ""),
            "extracted_text": None,
            "contract_data": None,
            "processing_result": None,
            "messages": []
        }

        logger.info("Starting PDF agent processing with structured state")

        try:
            final_state = await pdf_agent.ainvoke(initial_state)
            processing_result = final_state.get("processing_result")
            extracted_text = final_state.get("extracted_text") or ""

            if not processing_result:
                workflow_tracker.error_agent(execution, "No processing result returned")
                workflow_tracker.complete_workflow()
                return {
                    "status": "error",
                    "filename": request.filename,
                    "final_result": "No processing result returned",
                    "contract_id": None
                }, ""

            if processing_result.contract_id:
                workflow_tracker.complete_agent(execution, f"Contract stored with ID: {processing_result.contract_id}")
            else:
                workflow_tracker.error_agent(
                    execution, processing_result.error or processing_result.message or "Contract not stored")
            workflow_tracker.complete_workflow()

            return {
                "status": processing_result.status.value,
                "filename": request.filename,
                "final_result": processing_result.message or processing_result.error
                or f"Processing {processing_result.status.value}",
                "contract_id": processing_result.contract_id,
                "error": processing_result.error
            }, extracted_text

        except Exception as e:
            workflow_tracker.error_agent(execution, f"Processing failed: {str(e)}")
            workflow_tracker.complete_workflow()
            logger.error(f"Agent processing failed: {e}", exc_info=True)
            return {
                "status": "error",
                "filename": request.filename,
                "final_result": f"Processing failed: {str(e)}",
                "contract_id": None
            }, ""

    def _cleanup_file(self, file_path: str):
        """Clean up temporary uploaded file"""
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup file {file_path}: {e}")


class DocumentServiceFactory:
    """Factory for creating document processing services"""

    @staticmethod
    def create_service(agent_manager):
        """Create document processing service with dependencies"""
        return DocumentProcessingService(agent_manager)
