"""Per-request identity context (tenant and role).

Set once per request from the authenticated identity (see governance/rbac.py)
and read by tools the LLM calls, so the model can never choose which tenant's
data it searches.
"""
import contextvars

DEFAULT_TENANT = "default-tenant"

tenant_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default=DEFAULT_TENANT)
user_role_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_role", default="unknown")


def current_tenant() -> str:
    return tenant_id_var.get() or DEFAULT_TENANT
