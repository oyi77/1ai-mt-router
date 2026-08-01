import json
import os
from datetime import datetime, timedelta
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, BeforeValidator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.rbac import require_admin
from app.core.audit import write_audit_log
from app.core.database import get_db
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.database import (
    Instance,
    Invoice,
    SSHServer,
    User,
)
from app.services.billing_service import TIER_CONFIGS

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

TIER_OVERRIDES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "tier_overrides.json",
)


def _reject_bool(v):
    """Reject bools before pydantic's lax coercion turns them into 1/0.

    Pydantic v2 coerces JSON true/false to int 1/0 for ``int`` fields, so a
    handler-level ``type(...) is not int`` check never fires for bools. This
    validator runs before the int coercion and raises instead.
    """
    if type(v) is bool:
        raise ValueError("must be a non-negative integer (cents)")
    return v


StrictInt = Annotated[int, BeforeValidator(_reject_bool)]


class UserOut(BaseModel):
    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    two_factor_enabled: bool = False

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    full_name: Optional[str] = None


class TierUpdate(BaseModel):
    price_monthly: Optional[StrictInt] = None
    price_yearly: Optional[StrictInt] = None
    limits: Optional[Dict[str, Any]] = None
    features: Optional[List[str]] = None


class AnalyticsOut(BaseModel):
    total_users: int
    active_users: int
    total_instances: int
    running_instances: int
    total_servers: int
    total_revenue: int
    signups_last_30_days: int


class PaginatedUsers(BaseModel):
    items: List[UserOut]
    total: int
    skip: int
    limit: int


# ---------------------------------------------------------------------------
# Tier override helpers
# ---------------------------------------------------------------------------


def _load_tier_overrides() -> Dict[str, Any]:
    if not os.path.exists(TIER_OVERRIDES_PATH):
        return {}
    try:
        with open(TIER_OVERRIDES_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_tier_overrides(overrides: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(TIER_OVERRIDES_PATH), exist_ok=True)
    with open(TIER_OVERRIDES_PATH, "w") as f:
        json.dump(overrides, f, indent=2)


def _get_effective_tiers() -> Dict[str, Any]:
    """Return TIER_CONFIGS with any overrides merged on top."""
    import copy

    tiers = copy.deepcopy(TIER_CONFIGS)
    overrides = _load_tier_overrides()
    for tier_name, tier_overrides in overrides.items():
        if tier_name in tiers:
            if "limits" in tier_overrides:
                tiers[tier_name]["limits"].update(tier_overrides["limits"])
                tier_overrides_copy = {k: v for k, v in tier_overrides.items() if k != "limits"}
                tiers[tier_name].update(tier_overrides_copy)
            else:
                tiers[tier_name].update(tier_overrides)
    return tiers


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------


@router.get("/users", response_model=PaginatedUsers)
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users with pagination."""
    total = db.query(func.count(User.id)).scalar()
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return PaginatedUsers(
        items=[UserOut.model_validate(u) for u in users],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get a single user by ID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found", code="user_not_found")
    return UserOut.model_validate(user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update user fields (role, is_active, full_name)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    # Prevent admin from changing their own admin role
    if str(user.id) == current_user.get("sub") and payload.role and payload.role != "admin":
        raise BadRequestError("Cannot change your own admin role", code="self_role_change")

    changed = {}

    if payload.role is not None:
        valid_roles = {"admin", "user", "api_only"}
        if payload.role not in valid_roles:
            raise BadRequestError(
                f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                code="invalid_role",
            )
        user.role = payload.role
        changed["role"] = payload.role

    if payload.is_active is not None:
        user.is_active = payload.is_active
        changed["is_active"] = payload.is_active

    if payload.full_name is not None:
        user.full_name = payload.full_name
        changed["full_name"] = payload.full_name

    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    if changed:
        write_audit_log(
            db,
            action="admin.user.updated",
            user_id=int(current_user.get("sub")),
            resource_type="user",
            resource_id=str(user.id),
            details=changed,
        )

    return UserOut.model_validate(user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft-delete a user by deactivating their account."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    # Prevent admin from deleting themselves
    if str(user.id) == current_user.get("sub"):
        raise BadRequestError("Cannot delete your own account", code="self_delete")

    user.is_active = False
    user.updated_at = datetime.utcnow()
    db.commit()
    write_audit_log(
        db,
        action="admin.user.deactivated",
        user_id=int(current_user.get("sub")),
        resource_type="user",
        resource_id=str(user.id),
    )
    return {"detail": "User deactivated successfully"}


@router.post("/users/{user_id}/ban", response_model=UserOut)
def ban_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Ban a user by setting is_active to False."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if str(user.id) == current_user.get("sub"):
        raise BadRequestError("Cannot ban your own account", code="self_ban")

    user.is_active = False
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    write_audit_log(
        db,
        action="admin.user.banned",
        user_id=int(current_user.get("sub")),
        resource_type="user",
        resource_id=str(user.id),
    )
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/unban", response_model=UserOut)
def unban_user(
    user_id: int,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unban a user by setting is_active to True."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    user.is_active = True
    user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user)
    write_audit_log(
        db,
        action="admin.user.unbanned",
        user_id=int(current_user.get("sub")),
        resource_type="user",
        resource_id=str(user.id),
    )
    return UserOut.model_validate(user)


# ---------------------------------------------------------------------------
# Plan / Tier Management
# ---------------------------------------------------------------------------


@router.get("/tiers")
def list_tiers(
    current_user: dict = Depends(require_admin),
):
    """List all subscription tiers with any overrides applied."""
    tiers = _get_effective_tiers()
    return {
        "tiers": {
            name: {**config, "tier_name": name}
            for name, config in tiers.items()
        }
    }


@router.put("/tiers/{tier_name}")
def update_tier(
    tier_name: str,
    payload: TierUpdate,
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """
    Update tier pricing, limits, or features.

    Since tiers are hardcoded in billing_service.TIER_CONFIGS, changes
    are persisted as overrides in data/tier_overrides.json and merged
    at read time.
    """
    if tier_name not in TIER_CONFIGS:
        raise NotFoundError(
            f"Tier '{tier_name}' not found. Valid tiers: {', '.join(TIER_CONFIGS.keys())}",
            code="tier_not_found",
        )

    overrides = _load_tier_overrides()
    tier_override = overrides.get(tier_name, {})
    changed = {}

    if payload.price_monthly is not None:
        # type() is not int rejects bool (a subclass of int) so a JSON
        # true/false cannot silently become 1/0. The schema-level
        # StrictInt validator already rejects bools; this is defense-in-depth.
        if type(payload.price_monthly) is not int or payload.price_monthly < 0:
            raise BadRequestError(
                "price_monthly must be a non-negative integer (cents)",
                code="invalid_price",
            )
        tier_override["price_monthly"] = payload.price_monthly
        changed["price_monthly"] = payload.price_monthly
    if payload.price_yearly is not None:
        # type() is not int rejects bool (a subclass of int) so a JSON
        # true/false cannot silently become 1/0. The schema-level
        # StrictInt validator already rejects bools; this is defense-in-depth.
        if type(payload.price_yearly) is not int or payload.price_yearly < 0:
            raise BadRequestError(
                "price_yearly must be a non-negative integer (cents)",
                code="invalid_price",
            )
        tier_override["price_yearly"] = payload.price_yearly
        changed["price_yearly"] = payload.price_yearly
    if payload.limits is not None:
        existing_limits = tier_override.get("limits", {})
        for key, value in payload.limits.items():
            # Strict check: type() is not int rejects bool (a subclass of
            # int), so a JSON true/false cannot silently become 1/0.
            if type(value) is not int:
                raise BadRequestError(
                    f"limit '{key}' must be an integer",
                    code="invalid_limit",
                )
        existing_limits.update(payload.limits)
        tier_override["limits"] = existing_limits
        changed["limits"] = payload.limits
    if payload.features is not None:
        tier_override["features"] = payload.features
        changed["features"] = payload.features

    overrides[tier_name] = tier_override
    _save_tier_overrides(overrides)

    if changed:
        write_audit_log(
            db,
            action="admin.tier.updated",
            user_id=int(current_user.get("sub")),
            resource_type="tier",
            resource_id=tier_name,
            details=changed,
        )

    # Return the effective merged config
    effective = _get_effective_tiers()
    return {
        "detail": f"Tier '{tier_name}' updated successfully",
        "tier": {**effective[tier_name], "tier_name": tier_name},
    }


# ---------------------------------------------------------------------------
# Analytics Overview
# ---------------------------------------------------------------------------


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return high-level platform analytics."""
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)

    total_users = db.query(func.count(User.id)).scalar() or 0
    active_users = (
        db.query(func.count(User.id)).filter(User.is_active.is_(True)).scalar() or 0
    )

    total_instances = db.query(func.count(Instance.id)).scalar() or 0
    running_instances = (
        db.query(func.count(Instance.id))
        .filter(Instance.status == "running")
        .scalar()
        or 0
    )

    total_servers = db.query(func.count(SSHServer.id)).scalar() or 0

    # Total revenue from paid invoices (amount_cents is stored in cents)
    total_revenue = (
        db.query(func.coalesce(func.sum(Invoice.amount_cents), 0))
        .filter(Invoice.status == "paid")
        .scalar()
        or 0
    )

    signups_last_30_days = (
        db.query(func.count(User.id))
        .filter(User.created_at >= thirty_days_ago)
        .scalar()
        or 0
    )

    return AnalyticsOut(
        total_users=total_users,
        active_users=active_users,
        total_instances=total_instances,
        running_instances=running_instances,
        total_servers=total_servers,
        total_revenue=total_revenue,
        signups_last_30_days=signups_last_30_days,
    )
