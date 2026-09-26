import asyncio
from fastapi import APIRouter, HTTPException, Depends, Request
from backend.governance.rbac import Permission, requires_permission, get_current_tenant
from typing import Dict, Any
from ..agents.supervisor.supervisor_agent import SupervisorFactory, WorkflowRequest
from ..llm_manager import LLMManager
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)
router = APIRouter(prefix="/api/supervisor", tags=["supervisor"])

def get_llm_manager(request: Request):
    return request.app.state.llm_manager


_supervisor = None


def get_supervisor(llm_mgr: LLMManager):
    """One supervisor per process so workflow status and circuit breakers persist
    (a new supervisor per request meant status lookups always said 'not found')."""
    global _supervisor
    if _supervisor is None:
        _supervisor = SupervisorFactory.create_supervisor(llm_mgr)
    return _supervisor

@router.post("/workflow/execute", dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def execute_workflow(
    workflow_data: Dict[str, Any],
    llm_mgr: LLMManager = Depends(get_llm_manager),
    tenant_id: str = Depends(get_current_tenant),
):
    """Execute supervised workflow"""
    try:
        import uuid
        supervisor = get_supervisor(llm_mgr)
        input_data = dict(workflow_data.get("input_data", {}))
        input_data["tenant_id"] = tenant_id  # never trust a tenant from the body
        
        request = WorkflowRequest(
            workflow_id=workflow_data.get("workflow_id") or f"wf_{uuid.uuid4().hex[:12]}",
            workflow_type=workflow_data.get("workflow_type", "contract_analysis"),
            input_data=input_data
        )
        
        # Blocking multi-agent work runs off the event loop
        result = await asyncio.to_thread(supervisor.coordinate_workflow, request)
        
        return {
            "success": True,
            "workflow_id": result.workflow_id,
            "status": result.status,
            "results": result.results,
            "summary": result.summary
        }
        
    except Exception as e:
        logger.error(f"Supervisor workflow failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/workflow/{workflow_id}/status", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_workflow_status(
    workflow_id: str,
    llm_mgr: LLMManager = Depends(get_llm_manager),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get workflow status"""
    try:
        supervisor = get_supervisor(llm_mgr)
        context = supervisor.active_workflows.get(workflow_id)
        if context is None or context.get_shared_data("input_data", {}).get("tenant_id") != tenant_id:
            raise HTTPException(status_code=404, detail="Workflow not found")
        status = supervisor.get_workflow_status(workflow_id)
        return {"success": True, "status": status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))