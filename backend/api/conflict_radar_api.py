"""Cross-Contract Conflict Radar API.

PUT  /api/intelligence/contracts/{id}/governing-contract  link a contract (e.g. SOW) to its governing one (e.g. MSA)
POST /api/intelligence/contracts/{id}/conflicts           run a conflict check (replaces stored results)
GET  /api/intelligence/contracts/{id}/conflicts           last check's results
"""
import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.agents.conflict_judge_agent import ConflictJudge
from backend.application.services.conflict_detection_service import (
    ConflictDetectionFailedError,
    ConflictDetectionService,
    ContractNotFoundError,
    GoverningContractNotLinkedError,
)
from backend.governance.rbac import CurrentUser, Permission, get_current_user, requires_permission
from backend.infrastructure.audit_logger import AuditEventType, AuditLogger
from backend.llm_manager import DEFAULT_MODEL, LLMManager
from backend.shared.utils.logger import correlation_id_var, get_logger
from backend.shared.utils.utils import to_json_safe

logger = get_logger(__name__)

router = APIRouter(prefix="/api/intelligence", tags=["conflict-radar"])


class GoverningContractLink(BaseModel):
    governing_contract_id: str = Field(..., min_length=1)


def get_llm_manager(request: Request) -> LLMManager:
    return request.app.state.llm_manager


def get_conflict_service() -> ConflictDetectionService:
    return ConflictDetectionService()


def _traced_chat_model(llm_mgr: LLMManager, model: str):
    """Raw chat model tagged with the request's correlation id for LLM tracing."""
    llm = llm_mgr.get_chat_model(model)
    corr_id = correlation_id_var.get()
    return llm.with_config(tags=[f"correlation_id:{corr_id}"]) if corr_id else llm


def _internal_error(action: str, contract_id: str, error: Exception) -> HTTPException:
    """Log the details server-side; give the client only a reference to find them."""
    logger.error(f"{action} failed for contract {contract_id}: {error}", exc_info=True)
    return HTTPException(status_code=500,
                         detail=f"{action} failed (reference: {correlation_id_var.get() or 'n/a'})")


async def _audit(user: CurrentUser, event_type: AuditEventType, contract_id: str, action: str,
                 metadata: dict, status: str = "success") -> None:
    # AuditLogger writes to Neo4j synchronously; keep it off the event loop
    await asyncio.to_thread(
        AuditLogger().log_event, event_type=event_type, resource_id=contract_id, action=action,
        user_id=user.user_id, tenant_id=user.tenant_id, metadata=metadata, status=status)


@router.put("/contracts/{contract_id}/governing-contract",
            dependencies=[Depends(requires_permission(Permission.UPLOAD))])
async def link_governing_contract(
    contract_id: str,
    body: GoverningContractLink,
    user: CurrentUser = Depends(get_current_user),
    service: ConflictDetectionService = Depends(get_conflict_service),
):
    try:
        linked = await asyncio.to_thread(
            service.link_governing_contract, contract_id, body.governing_contract_id, user.tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ContractNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _internal_error("Linking", contract_id, e)

    await _audit(user, AuditEventType.DOCUMENT_UPDATE, contract_id, "link_governing_contract",
                 {"governing_contract_id": body.governing_contract_id})
    return to_json_safe(linked)


@router.post("/contracts/{contract_id}/conflicts",
             dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def detect_conflicts(
    contract_id: str,
    model: str = Query(default=DEFAULT_MODEL, description="LLM model used to judge clause pairs"),
    user: CurrentUser = Depends(get_current_user),
    llm_mgr: LLMManager = Depends(get_llm_manager),
    service: ConflictDetectionService = Depends(get_conflict_service),
):
    try:
        judge = ConflictJudge(_traced_chat_model(llm_mgr, model))
    except ValueError as e:  # no LLM configured
        raise HTTPException(status_code=503, detail=str(e))

    try:
        result = await asyncio.to_thread(service.detect_conflicts, contract_id, user.tenant_id, judge, model)
        response = await asyncio.to_thread(service.get_conflicts, contract_id, user.tenant_id)
    except ContractNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except GoverningContractNotLinkedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ConflictDetectionFailedError as e:
        raise HTTPException(status_code=502, detail=f"Conflict check failed: {e}")
    except Exception as e:
        raise _internal_error("Conflict check", contract_id, e)

    await _audit(user, AuditEventType.ANALYSIS_REQUEST, contract_id, "detect_conflicts",
                 {"model": model, "governing_contract_id": result.governing_contract_id,
                  "pairs_checked": result.pairs_checked, "pairs_failed": result.pairs_failed,
                  "pairs_truncated": result.pairs_truncated, "conflicts": len(result.findings)},
                 status=result.status)
    return to_json_safe(response)


@router.get("/contracts/{contract_id}/conflicts",
            dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_conflicts(
    contract_id: str,
    user: CurrentUser = Depends(get_current_user),
    service: ConflictDetectionService = Depends(get_conflict_service),
):
    try:
        return to_json_safe(await asyncio.to_thread(service.get_conflicts, contract_id, user.tenant_id))
    except ContractNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _internal_error("Reading conflicts", contract_id, e)
