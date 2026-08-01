from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import bcrypt
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

from app.config import settings
from app.core.database import get_db
from app.models.database import User
from app.auth.jwt import create_access_token, verify_token
from app.services import auth_enhancement_service
from app.services.encryption import encryption_service

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str
    two_factor_code: Optional[str] = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class VerifyEmailRequest(BaseModel):
    token: str


class TwoFactorSetupResponse(BaseModel):
    secret: str
    qr_uri: str


class TwoFactorVerifyRequest(BaseModel):
    code: str


@router.post("/login")
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter((User.username == request.username) | (User.email == request.username))
        .first()
    )

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.locked_until and user.locked_until > datetime.utcnow():
        raise HTTPException(status_code=423, detail="Account temporarily locked")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    if not bcrypt.checkpw(
        request.password.encode("utf-8"), user.hashed_password.encode("utf-8")
    ):
        user.failed_login_attempts += 1
        if auth_enhancement_service.auth_enhancement_service:
            lockout = auth_enhancement_service.auth_enhancement_service.calculate_lockout(
                user.failed_login_attempts
            )
            if lockout:
                user.locked_until = lockout
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if user.two_factor_enabled:
        if not request.two_factor_code:
            return {"requires_2fa": True, "message": "Enter 2FA code"}

        try:
            secret = encryption_service.decrypt(user.two_factor_secret)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid 2FA code")

        if not auth_enhancement_service.auth_enhancement_service or not (
            auth_enhancement_service.auth_enhancement_service.verify_2fa_token(
                secret, request.two_factor_code
            )
        ):
            raise HTTPException(status_code=401, detail="Invalid 2FA code")

    if not user.is_verified:
        return {"requires_verification": True, "message": "Please verify your email"}

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role}
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRATION_HOURS * 3600,
        "user": {
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "two_factor_enabled": user.two_factor_enabled,
        },
    }


@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    if (
        db.query(User)
        .filter((User.email == request.email) | (User.username == request.username))
        .first()
    ):
        raise HTTPException(status_code=400, detail="User already exists")

    verification_token = None
    verification_expires = None
    is_verified = True

    email_configured = bool(settings.SMTP_HOST and settings.FROM_EMAIL)

    if email_configured and auth_enhancement_service.auth_enhancement_service:
        verification_token, verification_expires = (
            auth_enhancement_service.auth_enhancement_service.generate_verification_token()
        )
        is_verified = False

    user = User(
        email=request.email,
        username=request.username,
        hashed_password=bcrypt.hashpw(
            request.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8"),
        full_name=request.full_name,
        is_verified=is_verified,
        verification_token=verification_token,
        verification_token_expires=verification_expires,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    if email_configured and auth_enhancement_service.auth_enhancement_service and verification_token:
        await auth_enhancement_service.auth_enhancement_service.send_verification_email(
            user.email, verification_token
        )

    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role}
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "requires_verification": not is_verified,
        "user": {"id": user.id, "email": user.email, "username": user.username},
    }


@router.post("/verify-email")
async def verify_email(request: VerifyEmailRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(
            User.verification_token == request.token,
            User.verification_token_expires > datetime.utcnow(),
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.is_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    db.commit()

    return {"status": "verified", "message": "Email verified successfully"}


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest, db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.email == request.email).first()

    if not user:
        return {"message": "If the email exists, a reset link has been sent"}

    if auth_enhancement_service.auth_enhancement_service:
        reset_token, reset_expires = auth_enhancement_service.auth_enhancement_service.generate_reset_token()
        user.reset_token = reset_token
        user.reset_token_expires = reset_expires
        db.commit()

        await auth_enhancement_service.auth_enhancement_service.send_password_reset_email(
            user.email, reset_token
        )

    return {"message": "If the email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = (
        db.query(User)
        .filter(
            User.reset_token == request.token,
            User.reset_token_expires > datetime.utcnow(),
        )
        .first()
    )

    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.hashed_password = bcrypt.hashpw(
        request.new_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    user.reset_token = None
    user.reset_token_expires = None
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()

    return {"status": "reset", "message": "Password reset successfully"}


@router.post("/2fa/setup")
async def setup_2fa(user: dict = Depends(verify_token), db: Session = Depends(get_db)):
    if not auth_enhancement_service.auth_enhancement_service:
        raise HTTPException(status_code=500, detail="2FA not configured")

    db_user = db.query(User).filter(User.id == int(user["sub"])).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if db_user.two_factor_enabled:
        raise HTTPException(status_code=400, detail="2FA already enabled")

    secret = auth_enhancement_service.auth_enhancement_service.generate_2fa_secret()
    qr_uri = auth_enhancement_service.auth_enhancement_service.get_2fa_uri(secret, db_user.email)

    db_user.two_factor_secret = encryption_service.encrypt(secret)
    db.commit()

    return {
        "secret": secret,
        "qr_uri": qr_uri,
        "message": "Scan QR code with authenticator app, then verify with /2fa/verify",
    }


@router.post("/2fa/verify")
async def verify_2fa(
    request: TwoFactorVerifyRequest,
    user: dict = Depends(verify_token),
    db: Session = Depends(get_db),
):
    if not auth_enhancement_service.auth_enhancement_service:
        raise HTTPException(status_code=500, detail="2FA not configured")

    db_user = db.query(User).filter(User.id == int(user["sub"])).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if not db_user.two_factor_secret:
        raise HTTPException(
            status_code=400, detail="2FA not set up. Call /2fa/setup first"
        )

    try:
        secret = encryption_service.decrypt(db_user.two_factor_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid code. Try again.")

    if not auth_enhancement_service.auth_enhancement_service.verify_2fa_token(secret, request.code):
        raise HTTPException(status_code=400, detail="Invalid code. Try again.")

    db_user.two_factor_enabled = True
    db.commit()

    if auth_enhancement_service.auth_enhancement_service:
        await auth_enhancement_service.auth_enhancement_service.send_2fa_enabled_email(db_user.email)

    return {"status": "enabled", "message": "2FA enabled successfully"}


@router.post("/2fa/disable")
async def disable_2fa(
    user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.id == int(user["sub"])).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    db_user.two_factor_enabled = False
    db_user.two_factor_secret = None
    db.commit()

    return {"status": "disabled", "message": "2FA disabled"}


@router.get("/security")
async def get_security_info(
    user: dict = Depends(verify_token), db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.id == int(user["sub"])).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "two_factor_enabled": db_user.two_factor_enabled,
        "email_verified": db_user.is_verified,
        "last_login": db_user.last_login.isoformat() if db_user.last_login else None,
        "failed_login_attempts": db_user.failed_login_attempts,
        "account_locked": db_user.locked_until
        and db_user.locked_until > datetime.utcnow(),
    }


@router.get("/me")
async def get_me(token: dict = Depends(verify_token)):
    return {
        "id": token.get("sub"),
        "username": token.get("username"),
        "role": token.get("role"),
    }
