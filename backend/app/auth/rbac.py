from fastapi import Depends, HTTPException, status

from app.auth.jwt import verify_token


def require_role(*roles: str):
    """
    FastAPI dependency that enforces role-based access control.

    Validates that the authenticated user's JWT contains a role
    matching one of the allowed roles. Returns 403 Forbidden if
    the user lacks the required role.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_endpoint(): ...

        @router.get("/multi-role")
        async def multi_role_endpoint(user=Depends(require_role("admin", "user"))): ...
    """
    allowed_roles = set(roles)

    def _role_checker(token: dict = Depends(verify_token)):
        user_role = token.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(allowed_roles)}",
            )
        return token

    return _role_checker


# Convenience shortcut for admin-only endpoints
require_admin = require_role("admin")
