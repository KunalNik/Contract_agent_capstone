"""Policy management API extending existing patterns."""

import os
import tempfile

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from backend.governance.rbac import Permission, requires_permission, get_current_user, get_current_tenant, CurrentUser
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from backend.application.services.policy_service import PolicyService
from backend.infrastructure.policy_repository import PolicyRepository
from backend.agents.policy_agents import PolicyComplianceAgent
from backend.agents.supervisor.interfaces import AgentContext
from backend.shared.utils.utils import to_json_safe

router = APIRouter(prefix="/api/policies", tags=["Policy Management"])

MAX_POLICY_BYTES = 20 * 1024 * 1024


class PolicyComplianceRequest(BaseModel):
    contract_clauses: List[Dict[str, Any]]
    contract_type: str = "general"
    contract_id: Optional[str] = None


class PolicySearchRequest(BaseModel):
    query: str
    contract_type: Optional[str] = None
    limit: int = 10


def extract_policy_text(filename: str, content: bytes) -> str:
    """Decode a policy upload: text files as UTF-8, PDFs via the PDF extractors."""
    name = (filename or "").lower()
    if name.endswith(".pdf") or content[:5] == b"%PDF-":
        from backend.infrastructure.text_extractors import TextExtractionService
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(content)
            path = tmp.name
        try:
            return TextExtractionService().extract_with_fallback(path)
        finally:
            os.remove(path)
    if name.endswith((".txt", ".md")) or "." not in name:
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Text policy files must be UTF-8 encoded")
    raise HTTPException(status_code=415, detail="Unsupported policy format; upload PDF or TXT")


@router.post("/upload", dependencies=[Depends(requires_permission(Permission.MANAGE_POLICIES))])
async def upload_policy_document(
    file: UploadFile = File(...),
    policy_name: str = Form(...),
    policy_type: str = Form("compliance"),
    version: str = Form("1.0"),
    user: CurrentUser = Depends(get_current_user),
):
    """Upload and process policy document using service layer."""
    tenant_id = user.tenant_id
    try:
        content = await file.read()
        if len(content) > MAX_POLICY_BYTES:
            raise HTTPException(status_code=400, detail="Policy file too large (max 20MB)")
        policy_text = extract_policy_text(file.filename, content)
        
        policy_data = {
            'policy_text': policy_text,
            'tenant_id': tenant_id,
            'policy_name': policy_name,
            'policy_type': policy_type,
            'version': version
        }
        
        # Use service layer
        policy_service = PolicyService()
        result = await policy_service.upload_and_process_policy(policy_data, user_id=user.user_id)
        
        if not result['success']:
            raise HTTPException(status_code=400, detail=result['error'])
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tenant", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_tenant_policies(tenant_id: str = Depends(get_current_tenant)):
    """Get all active policies for the caller's tenant."""
    result = PolicyService().get_tenant_policies(tenant_id)
    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error'))
    return to_json_safe(result)


@router.get("/tenant/{requested_tenant}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_tenant_policies_legacy(requested_tenant: str, tenant_id: str = Depends(get_current_tenant)):
    """Backward-compatible path; a caller can only list their own tenant's policies."""
    if requested_tenant != tenant_id:
        raise HTTPException(status_code=403, detail="Cannot list another tenant's policies")
    return await get_tenant_policies(tenant_id)


@router.get("/{policy_id}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_policy_details(policy_id: str, tenant_id: str = Depends(get_current_tenant)):
    """Get detailed policy information."""
    try:
        repository = PolicyRepository()
        policy = repository.get_policy_by_id(policy_id, tenant_id=tenant_id)
        
        if not policy:
            raise HTTPException(status_code=404, detail="Policy not found")
        
        return {
            'success': True,
            'policy': {
                'id': policy.id,
                'name': policy.name,
                'tenant_id': policy.tenant_id,
                'version': policy.version,
                'created_at': to_json_safe(policy.created_at),
                'rules': [
                    {
                        'id': rule.id,
                        'rule_text': rule.rule_text,
                        'rule_type': rule.rule_type,
                        'applies_to': rule.applies_to,
                        'severity': rule.severity,
                        'section_reference': rule.section_reference
                    }
                    for rule in policy.rules
                ]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compliance/check", dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def check_policy_compliance(request: PolicyComplianceRequest, tenant_id: str = Depends(get_current_tenant)):
    """Check contract compliance against policies using existing agent."""
    try:
        compliance_agent = PolicyComplianceAgent()
        
        context = AgentContext(
            input_data={
                'tenant_id': tenant_id,
                'clauses': request.contract_clauses,
                'contract_type': request.contract_type
            },
            workflow_context=None
        )
        
        result = compliance_agent.execute(context)
        
        if result.status != 'success':
            raise HTTPException(status_code=500, detail=result.data.get('error'))
        
        from backend.infrastructure.policy_audit_service import PolicyAuditService
        PolicyAuditService().log_policy_compliance_check(tenant_id, request.contract_id, result.data)
        return {
            'success': True,
            'compliance_check': {
                'violations_found': result.data['violations_found'],
                'policies_checked': result.data['policies_checked'],
                'violations': result.data['violations']
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", dependencies=[Depends(requires_permission(Permission.ANALYZE))])
async def search_policies(request: PolicySearchRequest, user: CurrentUser = Depends(get_current_user)):
    """Search policies using semantic similarity."""
    try:
        result = PolicyService().search_policies(user.tenant_id, request.query, request.limit, user.user_id)
        if not result.get('success'):
            raise HTTPException(status_code=500, detail=result.get('error'))
        return result
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/applicable/{contract_type}", dependencies=[Depends(requires_permission(Permission.VIEW_REPORTS))])
async def get_applicable_policies(contract_type: str, tenant_id: str = Depends(get_current_tenant)):
    """Get policies applicable to specific contract type (caller's tenant)."""
    try:
        repository = PolicyRepository()
        policies = repository.get_applicable_policies(tenant_id, contract_type)
        
        return {
            'success': True,
            'tenant_id': tenant_id,
            'contract_type': contract_type,
            'applicable_policies': [
                {
                    'id': policy.id,
                    'rule_text': policy.rule_text[:100] + '...' if len(policy.rule_text) > 100 else policy.rule_text,
                    'rule_type': policy.rule_type,
                    'severity': policy.severity,
                    'applies_to': policy.applies_to
                }
                for policy in policies
            ]
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{policy_id}", dependencies=[Depends(requires_permission(Permission.MANAGE_POLICIES))])
async def delete_policy(policy_id: str, user: CurrentUser = Depends(get_current_user)):
    """Soft delete policy (caller's tenant only)."""
    try:
        repository = PolicyRepository()
        if not repository.delete_policy(policy_id, tenant_id=user.tenant_id):
            raise HTTPException(status_code=404, detail="Policy not found")

        from backend.infrastructure.policy_audit_service import PolicyAuditService
        from backend.infrastructure.policy_cache_service import PolicyCacheService
        PolicyCacheService().invalidate_policy_cache(user.tenant_id, policy_id)
        PolicyAuditService().log_policy_deletion(user.tenant_id, policy_id, policy_id, user.user_id)
        return {
            'success': True,
            'message': f'Policy {policy_id} deleted successfully'
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
async def get_policy_capabilities():
    """Get policy management capabilities."""
    return {
        'capabilities': {
            'document_processing': 'Upload and process 50+ page policy documents',
            'rule_extraction': 'Extract mandatory, recommended, and prohibited rules',
            'semantic_search': 'Search policies using natural language queries',
            'compliance_checking': 'Check contract compliance against policies',
            'multi_tenancy': 'Tenant-isolated policy management',
            'versioning': 'Policy version control and history tracking'
        },
        'supported_formats': ['PDF', 'TXT'],
        'rule_types': ['mandatory', 'recommended', 'prohibited', 'general'],
        'severity_levels': ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'],
        'contract_types': [
            'liability', 'termination', 'payment', 'confidentiality',
            'intellectual_property', 'data_protection', 'general'
        ]
    }