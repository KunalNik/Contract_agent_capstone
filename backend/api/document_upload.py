import hashlib
import json
import os
import re
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, Depends, Request
from fastapi.responses import StreamingResponse

from backend.governance.rbac import Permission, requires_permission, get_current_user, CurrentUser
from backend.application.services.document_processing_service import DocumentServiceFactory, get_chat_model
from backend.domain.entities import DocumentProcessingRequest
from backend.llm_manager import LLMManager
from backend.infrastructure.audit_logger import AuditLogger, AuditEventType
from backend.infrastructure.content_validator import ContentValidationService
from backend.infrastructure.error_tracker import ErrorTracker, ErrorCategory, ErrorSeverity, ErrorContext
from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

# Create router
router = APIRouter(prefix="/api/documents", tags=["documents"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_DIR = os.getenv("UPLOAD_TMP_DIR", "/tmp")


# Dependency injection
def get_llm_manager(request: Request):
    return request.app.state.llm_manager


def safe_temp_path(filename: str) -> str:
    """Temp path that cannot escape UPLOAD_DIR whatever the client sends as filename."""
    base = os.path.basename(filename or "upload.pdf")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:100] or "upload.pdf"
    return os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_{base}")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_duplicate_contract(tenant_id: str, digest: str):
    """Existing contract with identical bytes for this tenant (None if none / DB error)."""
    from backend.infrastructure.contract_repository import Neo4jContractRepository
    try:
        return Neo4jContractRepository().find_duplicate(tenant_id, digest)
    except Exception as e:
        logger.error(f"Duplicate check query failed: {e}")
        return None


async def chunk_contract_in_background(contract_id: str, full_text: str, filename: str, tenant_id: str):
    """Chunk + embed the stored contract. Runs after the response is sent."""
    try:
        from backend.agents.chunking_agent import ChunkingAgent
        result = await ChunkingAgent().process_document(
            document_id=contract_id,
            content=full_text,
            metadata={"filename": filename, "document_type": "contract", "tenant_id": tenant_id},
        )
        logger.info(f"Chunking finished for {contract_id}: {result.get('chunk_count', 0)} chunks")
    except Exception as e:
        logger.warning(f"Chunking failed for {contract_id} (contract is still stored): {e}")


@router.post("/upload", dependencies=[Depends(requires_permission(Permission.UPLOAD))])
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    model: str = Query(default="gemini-2.5-flash", description="LLM model to use for processing"),
    enable_enhanced: bool = Query(default=False, description="Enable enhanced processing with sections/clauses"),
    llm_mgr: LLMManager = Depends(get_llm_manager),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Upload and process PDF contract
    - Validates file type and size
    - Rejects exact duplicates (same bytes) for the caller's tenant
    - Processes using PDF processing agent
    - Chunks and embeds the stored contract in the background
    """
    tenant_id = user.tenant_id
    logger.info(f"=== UPLOAD START: {file.filename if file else 'NO FILE'} ===")

    audit_logger = AuditLogger()
    validator = ContentValidationService()
    temp_path = None

    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        file_content = await file.read()
        validation_result = validator.validate_file_upload({
            "filename": file.filename,
            "file_size": len(file_content)
        })
        if not validation_result["is_valid"]:
            audit_logger.log_event(
                event_type=AuditEventType.VALIDATION_FAILURE,
                resource_id=file.filename,
                action="file_validation",
                tenant_id=tenant_id,
                status="failure",
                error_details=json.dumps(validation_result)
            )
            raise HTTPException(status_code=400, detail=f"Validation failed: {validation_result['summary']}")

        # Duplicate check by content hash, scoped to this tenant
        digest = content_hash(file_content)
        existing_id = find_duplicate_contract(tenant_id, digest)
        if existing_id:
            return {
                "message": "Duplicate file detected",
                "filename": file.filename,
                "status": "duplicate",
                "existing_contract_id": existing_id,
                "contract_id": existing_id,
                "action": "skipped"
            }

        temp_path = safe_temp_path(file.filename)
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)

        from backend.infrastructure.text_extractors import TextExtractionService
        full_text = TextExtractionService().extract_with_fallback(temp_path)
        content_validation = validator.validate({"full_text": full_text})
        if content_validation["has_errors"]:
            audit_logger.log_event(
                event_type=AuditEventType.VALIDATION_FAILURE,
                resource_id=file.filename,
                action="content_validation",
                tenant_id=tenant_id,
                status="failure",
                error_details=json.dumps(content_validation)
            )
            logger.warning(f"Content validation issues: {content_validation['summary']}")

        options = {
            "model": model,
            "full_text": full_text,
            "enable_enhanced": enable_enhanced,
            "tenant_id": tenant_id,
            "filename": file.filename,
            "content_hash": digest,
        }

        try:
            if enable_enhanced:
                from backend.factories.document_processor_factory import DocumentProcessorFactory
                processor = DocumentProcessorFactory.create_processor("full", get_chat_model(llm_mgr, model))
                raw = await processor.process_document(temp_path, options)
                result = {
                    "status": raw["status"],
                    "contract_id": raw.get("contract_id"),
                    "final_result": raw.get("error") or (
                        f"Enhanced processing {raw['status']}. Sections: {raw['sections_extracted']}, "
                        f"Clauses: {raw['clauses_extracted']}, CUAD: {raw['cuad_classifications']}"),
                }
            else:
                document_service = DocumentServiceFactory.create_service(llm_mgr)
                request = DocumentProcessingRequest(
                    file_path=temp_path, filename=file.filename, tenant_id=tenant_id,
                    user_id=user.user_id, processing_options=options,
                )
                result = await document_service.process_pdf_upload(request, background_tasks=background_tasks)
        except Exception as proc_error:
            logger.error(f"Document processing failed: {proc_error}", exc_info=True)
            audit_logger.log_event(
                event_type=AuditEventType.PROCESSING_ERROR,
                resource_id=file.filename,
                action="document_processing",
                tenant_id=tenant_id,
                status="failure",
                error_details=str(proc_error)
            )
            return {
                "message": "PDF processing failed",
                "filename": file.filename,
                "status": "error",
                "contract_id": None,
                "details": f"Processing error: {str(proc_error)}",
                "model_used": model,
                "error_type": type(proc_error).__name__
            }

        contract_id = result.get("contract_id")
        if contract_id:
            background_tasks.add_task(chunk_contract_in_background, contract_id, full_text, file.filename, tenant_id)

        audit_logger.log_event(
            event_type=AuditEventType.DOCUMENT_UPLOAD,
            resource_id=contract_id or file.filename,
            action="upload_completed",
            user_id=user.user_id,
            tenant_id=tenant_id,
            status="success" if contract_id else "failure",
            metadata={"filename": file.filename, "model": model, "result_status": result.get("status")}
        )

        return {
            "message": "PDF processing completed",
            "filename": file.filename,
            "status": result["status"],
            "contract_id": contract_id,
            "details": result.get("final_result", ""),
            "model_used": model,
            "validation_passed": True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"=== UPLOAD FAILED: {file.filename if file else 'unknown'}: {e}", exc_info=True)
        ErrorTracker().track_error(
            error=e,
            category=ErrorCategory.FILE_ERROR,
            severity=ErrorSeverity.HIGH,
            context=ErrorContext(operation="document_upload", resource_id=file.filename,
                                 user_id=user.user_id, tenant_id=tenant_id, metadata={"model": model}),
        )
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as cleanup_error:
                logger.error(f"Failed to cleanup temp file: {cleanup_error}")
        logger.info(f"=== UPLOAD END: {file.filename if file else 'unknown'} ===")


@router.post("/upload-stream", dependencies=[Depends(requires_permission(Permission.UPLOAD))])
async def upload_pdf_stream(
    file: UploadFile = File(...),
    model: str = Query(default="gemini-2.5-flash", description="LLM model to use for processing"),
    llm_mgr: LLMManager = Depends(get_llm_manager),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Upload and process PDF with streaming progress events (one per pipeline step).
    """
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file")

    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File too large")

    temp_path = safe_temp_path(file.filename)
    with open(temp_path, "wb") as temp_file:
        temp_file.write(file_content)

    tenant_id = user.tenant_id
    digest = content_hash(file_content)
    step_labels = {
        "extract_text": "Extracted text from PDF",
        "analyze_contract": "Analyzed contract structure",
        "store_contract": "Stored contract",
    }

    async def stream_processing():
        try:
            existing_id = find_duplicate_contract(tenant_id, digest)
            if existing_id:
                yield f"data: {json.dumps({'content': f'Duplicate of {existing_id}', 'type': 'completion', 'contract_id': existing_id})}\n\n"
                return

            from backend.agents.pdf_processing_agent import PDFAgentFactory
            pdf_agent = PDFAgentFactory.create_agent(get_chat_model(llm_mgr, model))
            initial_state = {
                "file_path": temp_path,
                "tenant_id": tenant_id,
                "filename": file.filename,
                "content_hash": digest,
                "messages": [],
                "extracted_text": None,
                "contract_data": None,
                "processing_result": None,
            }

            final_result = None
            async for update in pdf_agent.astream(initial_state, stream_mode="updates"):
                for node, node_state in update.items():
                    yield f"data: {json.dumps({'content': step_labels.get(node, node), 'type': 'progress', 'step': node})}\n\n"
                    if node_state and node_state.get("processing_result") is not None:
                        final_result = node_state["processing_result"]

            status = final_result.status.value if final_result else "error"
            message = (final_result.message or final_result.error) if final_result else "No result"
            yield f"data: {json.dumps({'content': message, 'type': 'completion', 'status': status, 'contract_id': getattr(final_result, 'contract_id', None)})}\n\n"

        except Exception as e:
            logger.error(f"Streaming PDF upload failed: {e}", exc_info=True)
            yield f"data: {json.dumps({'content': f'Processing failed: {str(e)}', 'type': 'error'})}\n\n"
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            yield f"data: {json.dumps({'content': '', 'type': 'end'})}\n\n"

    return StreamingResponse(
        stream_processing(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/status")
async def get_upload_status(llm_mgr: LLMManager = Depends(get_llm_manager)):
    """Get system status for document uploads"""
    return {
        "status": "operational",
        "supported_formats": ["pdf"],
        "max_file_size": "50MB",
        "available_models": list(llm_mgr.agents.keys())
    }
