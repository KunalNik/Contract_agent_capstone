"""
Audit Trail API Endpoints
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from backend.governance.rbac import Permission, requires_permission, get_current_tenant
from backend.infrastructure.audit_logger import AuditLogger
from backend.infrastructure.error_tracker import ErrorTracker
from typing import Optional
import logging

from backend.shared.utils.logger import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api/audit", tags=["audit"])

@router.get("/trail/{resource_id}", dependencies=[Depends(requires_permission(Permission.VIEW_AUDIT))])
async def get_audit_trail(
    resource_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get audit trail for a specific resource"""
    try:
        audit_logger = AuditLogger()
        trail = audit_logger.get_audit_trail(resource_id, limit, tenant_id=tenant_id)
        
        return {
            "resource_id": resource_id,
            "total_events": len(trail),
            "events": trail
        }
        
    except Exception as e:
        logger.error(f"Failed to get audit trail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/errors/statistics", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_error_statistics(
    hours: int = Query(default=24, ge=1, le=168),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get error statistics for monitoring"""
    try:
        error_tracker = ErrorTracker()
        stats = error_tracker.get_error_statistics(hours, tenant_id=tenant_id)
        
        return {
            "time_window_hours": hours,
            "statistics": stats
        }
        
    except Exception as e:
        logger.error(f"Failed to get error statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/errors/recent", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_recent_errors(
    limit: int = Query(default=50, ge=1, le=500),
    tenant_id: str = Depends(get_current_tenant),
):
    """Get recent errors for debugging"""
    try:
        error_tracker = ErrorTracker()
        errors = error_tracker.get_recent_errors(limit, tenant_id=tenant_id)
        
        return {
            "total_errors": len(errors),
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Failed to get recent errors: {e}")
        raise HTTPException(status_code=500, detail=str(e))
