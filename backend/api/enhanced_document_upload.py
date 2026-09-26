from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends, Request
from backend.governance.rbac import Permission, requires_permission, get_current_user, get_current_tenant, CurrentUser
from backend.api.document_upload import MAX_UPLOAD_BYTES, content_hash, find_duplicate_contract, safe_temp_path
from backend.application.services.enhanced_document_processing_service import EnhancedDocumentServiceFactory
from backend.domain.entities import DocumentProcessingRequest
from backend.llm_manager import LLMManager
import os

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

# Create router
router = APIRouter(prefix="/api/documents/enhanced", tags=["enhanced-documents"])

# Dependency injection
def get_llm_manager(request: Request):
    return request.app.state.llm_manager

@router.post("/upload", dependencies=[Depends(requires_permission(Permission.UPLOAD))])
async def upload_pdf_enhanced(
    file: UploadFile = File(...),
    model: str = Query(default="gemini-2.5-flash", description="LLM model to use for processing"),
    enable_embeddings: bool = Query(default=True, description="Enable multi-level embeddings processing"),
    llm_mgr: LLMManager = Depends(get_llm_manager),
    user: CurrentUser = Depends(get_current_user),
):
    """
    Upload and process PDF contract with enhanced multi-level embeddings
    - Validates file type and size
    - Rejects exact duplicates (same bytes) for the caller's tenant
    - Generates document, section, clause, and relationship embeddings
    - Returns processing status with embedding details
    """
    tenant_id = user.tenant_id
    logger.info(f"=== ENHANCED UPLOAD START: {file.filename if file else 'NO FILE'} ===")
    temp_path = None

    try:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")

        file_content = await file.read()
        if len(file_content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large (max 50MB)")

        digest = content_hash(file_content)
        existing_id = find_duplicate_contract(tenant_id, digest)
        if existing_id:
            return {
                "message": "Duplicate file detected",
                "filename": file.filename,
                "status": "duplicate",
                "existing_contract_id": existing_id,
                "contract_id": existing_id,
                "action": "skipped",
                "enhanced_embeddings": False
            }

        temp_path = safe_temp_path(file.filename)
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)

        processing_request = DocumentProcessingRequest(
            file_path=temp_path,
            filename=file.filename,
            tenant_id=tenant_id,
            user_id=user.user_id,
            processing_options={"model": model, "enable_embeddings": enable_embeddings, "content_hash": digest},
        )

        try:
            if enable_embeddings:
                service = EnhancedDocumentServiceFactory.create_service(llm_mgr)
                result = await service.process_pdf_with_embeddings(processing_request)
            else:
                from backend.application.services.document_processing_service import DocumentServiceFactory
                result = await DocumentServiceFactory.create_service(llm_mgr).process_pdf_upload(processing_request)
                result["enhanced_embeddings"] = False
        except Exception as proc_error:
            logger.error(f"Enhanced document processing failed: {proc_error}", exc_info=True)
            return {
                "message": "Enhanced PDF processing failed",
                "filename": file.filename,
                "status": "error",
                "contract_id": None,
                "details": f"Processing error: {str(proc_error)}",
                "model_used": model,
                "enhanced_embeddings": False,
                "error_type": type(proc_error).__name__
            }

        return {
            "message": "Enhanced PDF processing completed",
            "filename": file.filename,
            "status": result["status"],
            "contract_id": result.get("contract_id"),
            "details": result.get("final_result", ""),
            "model_used": model,
            "enhanced_embeddings": result.get("enhanced_embeddings", False),
            "embedding_types": ["document", "section", "clause", "relationship"] if result.get("enhanced_embeddings") else []
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"=== ENHANCED UPLOAD FAILED: {file.filename if file else 'unknown'}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Enhanced processing failed: {str(e)}")
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
        logger.info(f"=== ENHANCED UPLOAD END: {file.filename if file else 'unknown'} ===")

@router.get("/embedding-status/{contract_id}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_embedding_status(contract_id: str, tenant_id: str = Depends(get_current_tenant)):
    """Get embedding status for a specific contract"""
    try:
        from backend.shared.utils.contract_search_tool import graph
        
        # Check embedding status
        query = """
        MATCH (c:Contract {file_id: $contract_id, tenant_id: $tenant_id})
        OPTIONAL MATCH (c)-[:HAS_SECTION]->(s:Section)
        OPTIONAL MATCH (c)-[:HAS_SECTION|CONTAINS_CLAUSE*1..2]->(cl:Clause)
        OPTIONAL MATCH (c)<-[r:PARTY_TO]-()
        RETURN 
            c.document_embedding IS NOT NULL as has_document_embedding,
            c.summary_embedding IS NOT NULL as has_summary_embedding,
            count(DISTINCT s) as section_count,
            count(DISTINCT CASE WHEN s.embedding IS NOT NULL THEN s END) as section_embeddings,
            count(DISTINCT cl) as clause_count,
            count(DISTINCT CASE WHEN cl.embedding IS NOT NULL THEN cl END) as clause_embeddings,
            count(DISTINCT r) as relationship_count,
            count(DISTINCT CASE WHEN r.embedding IS NOT NULL THEN r END) as relationship_embeddings
        """
        
        result = graph.query(query, {"contract_id": contract_id, "tenant_id": tenant_id})
        
        if not result:
            raise HTTPException(status_code=404, detail="Contract not found")
        
        data = result[0]
        
        return {
            "contract_id": contract_id,
            "embedding_status": {
                "document_embedding": data["has_document_embedding"],
                "summary_embedding": data["has_summary_embedding"],
                "sections": {
                    "count": data["section_count"],
                    "embedded_count": data["section_embeddings"],
                    "has_embeddings": data["section_embeddings"] > 0
                },
                "clauses": {
                    "count": data["clause_count"],
                    "embedded_count": data["clause_embeddings"],
                    "has_embeddings": data["clause_embeddings"] > 0
                },
                "relationships": {
                    "count": data["relationship_count"],
                    "embedded_count": data["relationship_embeddings"],
                    "has_embeddings": data["relationship_embeddings"] > 0
                }
            },
            "total_embeddings": (
                (1 if data["has_document_embedding"] else 0) +
                (1 if data["has_summary_embedding"] else 0) +
                data["section_embeddings"] +
                data["clause_embeddings"] +
                data["relationship_embeddings"]
            )
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get embedding status for {contract_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get embedding status: {str(e)}")

@router.get("/status")
async def get_enhanced_upload_status(llm_mgr: LLMManager = Depends(get_llm_manager)):
    """Get system status for enhanced document uploads"""
    return {
        "status": "operational",
        "supported_formats": ["pdf"],
        "max_file_size": "50MB",
        "available_models": list(llm_mgr.agents.keys()),
        "embedding_features": {
            "document_level": True,
            "section_level": True,
            "clause_level": True,
            "relationship_level": True,
            "cuad_clause_types": 41,
            "validation": True
        }
    }