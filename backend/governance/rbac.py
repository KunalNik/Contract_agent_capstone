"""
Role-based access control and request identity.

Two authentication modes, chosen by ``AUTH_MODE`` (default: ``jwt`` when
``ENVIRONMENT=production``, otherwise ``header``):

* ``jwt``    - requires ``Authorization: Bearer <token>`` signed with
               ``JWT_SECRET`` (HS256). Claims: ``sub``, ``role``, ``tenant_id``.
               Missing or invalid tokens get 401. Headers cannot override claims.
* ``header`` - development only. Role from ``X-User-Role`` (defaults to
               ``DEV_DEFAULT_ROLE``, ADMIN if unset) and tenant from
               ``X-Tenant-ID`` (defaults to ``default-tenant``). Never enabled
               in production, so the old "no header => ADMIN" behaviour can no
               longer leak into a deployed system.

The resolved identity is stored in request context variables so tools and
services use the caller's tenant instead of a client- or LLM-supplied one.
"""
import os
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Set

from fastapi import Depends, Header, HTTPException, status

from backend.shared.utils.logger import get_logger
from backend.shared.utils.request_context import DEFAULT_TENANT, tenant_id_var, user_role_var

logger = get_logger(__name__)


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    LEGAL_REVIEWER = "LEGAL_REVIEWER"
    AUDITOR = "AUDITOR"
    VIEWER = "VIEWER"


class Permission(str, Enum):
    UPLOAD = "UPLOAD"
    DELETE = "DELETE"
    ANALYZE = "ANALYZE"
    VIEW_REPORTS = "VIEW_REPORTS"
    MANAGE_POLICIES = "MANAGE_POLICIES"
    VIEW_AUDIT = "VIEW_AUDIT"


class RBACManager:
    """
    Manager for Role-Based Access Control.
    Maps roles to permissions and provides validation logic.
    """

    ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
        UserRole.ADMIN: set(Permission),  # Admins have all permissions
        UserRole.LEGAL_REVIEWER: {
            Permission.ANALYZE,
            Permission.UPLOAD,
            Permission.VIEW_REPORTS
        },
        UserRole.AUDITOR: {
            Permission.VIEW_REPORTS,
            Permission.VIEW_AUDIT
        },
        UserRole.VIEWER: {
            Permission.ANALYZE  # Can query/analyze but not upload/delete
        }
    }

    @classmethod
    def has_permission(cls, role: UserRole, permission: Permission) -> bool:
        """Check if a role has a specific permission"""
        allowed_permissions = cls.ROLE_PERMISSIONS.get(role, set())
        return permission in allowed_permissions


@dataclass
class CurrentUser:
    user_id: str
    role: UserRole
    tenant_id: str


def auth_mode() -> str:
    mode = os.getenv("AUTH_MODE")
    if mode:
        return mode.lower()
    return "jwt" if os.getenv("ENVIRONMENT", "development") == "production" else "header"


def _parse_role(value: str) -> UserRole:
    try:
        return UserRole(value.upper())
    except (ValueError, AttributeError):
        logger.error(f"Invalid user role provided: {value}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid user role: {value}")


def _user_from_jwt(authorization: Optional[str]) -> CurrentUser:
    import jwt  # PyJWT

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    secret = os.getenv("JWT_SECRET")
    if not secret:
        logger.error("AUTH_MODE=jwt but JWT_SECRET is not set; rejecting request")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Authentication not configured")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["sub", "role", "tenant_id"]})
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return CurrentUser(user_id=str(claims["sub"]), role=_parse_role(claims["role"]), tenant_id=str(claims["tenant_id"]))


def _user_from_headers(x_user_role: Optional[str], x_tenant_id: Optional[str]) -> CurrentUser:
    if x_user_role:
        role = _parse_role(x_user_role)
    else:
        role = _parse_role(os.getenv("DEV_DEFAULT_ROLE", "ADMIN"))
        logger.warning(f"No X-User-Role header (development header auth); defaulting to {role.value}")
    return CurrentUser(user_id="dev-user", role=role, tenant_id=(x_tenant_id or DEFAULT_TENANT).strip())


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_user_role: Optional[str] = Header(None),
    x_tenant_id: Optional[str] = Header(None),
) -> CurrentUser:
    """Resolve the caller's identity and publish it to the request context."""
    mode = auth_mode()
    if mode == "jwt":
        user = _user_from_jwt(authorization)
    elif mode == "header":
        user = _user_from_headers(x_user_role, x_tenant_id)
    else:
        raise HTTPException(status_code=500, detail=f"Unknown AUTH_MODE '{mode}'")
    tenant_id_var.set(user.tenant_id)
    user_role_var.set(user.role.value)
    return user


async def get_current_user_role(user: CurrentUser = Depends(get_current_user)) -> UserRole:
    """Backward-compatible dependency returning only the role."""
    return user.role


async def get_current_tenant(user: CurrentUser = Depends(get_current_user)) -> str:
    return user.tenant_id


def requires_permission(permission: Permission):
    """
    FastAPI dependency factory for RBAC.
    Usage: @app.get("/...", dependencies=[Depends(requires_permission(Permission.UPLOAD))])
    """
    async def permission_dependency(role: UserRole = Depends(get_current_user_role)):
        if not RBACManager.has_permission(role, permission):
            logger.error(f"RBAC Denied: Role '{role.value}' attempted action requiring '{permission.value}'")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Resource requires '{permission.value}' permission which is not assigned to role '{role.value}'"
            )
        logger.info(f"RBAC Allowed: Role '{role.value}' authorized for '{permission.value}'")
        return True

    return permission_dependency


def create_access_token(user_id: str, role: str, tenant_id: str, expires_minutes: int = 60) -> str:
    """Issue an HS256 token (for tests, scripts and a future login endpoint)."""
    import datetime as _dt
    import jwt

    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + _dt.timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
