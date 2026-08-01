from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from app.core.database import get_db
from app.models.database import MT5Account, User
from app.auth.jwt import get_current_user
from app.services.encryption import encryption_service
from app.services.mt5_service import MT5Service

router = APIRouter()
logger = logging.getLogger(__name__)


class AccountCreateRequest(BaseModel):
    login: str
    password: str
    server: str
    broker: Optional[str] = None
    account_name: Optional[str] = None
    is_demo: bool = True
    instance_id: Optional[str] = None


class AccountUpdateRequest(BaseModel):
    account_name: Optional[str] = None
    broker: Optional[str] = None
    instance_id: Optional[str] = None


class AccountResponse(BaseModel):
    id: int
    login: str
    server: str
    broker: Optional[str]
    account_name: Optional[str]
    is_demo: bool
    connection_status: str
    connection_error: Optional[str]
    last_connected: Optional[datetime]
    created_at: datetime
    instance_id: Optional[str]

    class Config:
        from_attributes = True


def account_to_response(account: MT5Account) -> dict:
    return {
        "id": account.id,
        "login": account.login,
        "server": account.server,
        "broker": account.broker,
        "account_name": account.account_name,
        "is_demo": account.is_demo,
        "connection_status": account.connection_status,
        "connection_error": account.connection_error,
        "last_connected": account.last_connected,
        "created_at": account.created_at,
        "instance_id": account.instance_id,
    }


@router.post("", response_model=AccountResponse)
async def create_account(
    request: AccountCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    encrypted_password = encryption_service.encrypt(request.password)

    account = MT5Account(
        user_id=user_id,
        login=request.login,
        encrypted_password=encrypted_password,
        server=request.server,
        broker=request.broker,
        account_name=request.account_name,
        is_demo=request.is_demo,
        instance_id=request.instance_id,
        connection_status="disconnected",
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    logger.info(f"MT5 account created: {account.id} for user {user_id}")
    return account_to_response(account)


@router.get("", response_model=List[AccountResponse])
async def list_accounts(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    user_id = user.id
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    accounts = db.query(MT5Account).filter(MT5Account.user_id == user_id).all()
    return [account_to_response(acc) for acc in accounts]


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    account = (
        db.query(MT5Account)
        .filter(MT5Account.id == account_id, MT5Account.user_id == user_id)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    return account_to_response(account)


@router.put("/{account_id}", response_model=AccountResponse)
async def update_account(
    account_id: int,
    request: AccountUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    account = (
        db.query(MT5Account)
        .filter(MT5Account.id == account_id, MT5Account.user_id == user_id)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if request.account_name is not None:
        account.account_name = request.account_name
    if request.broker is not None:
        account.broker = request.broker
    if request.instance_id is not None:
        account.instance_id = request.instance_id

    account.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(account)

    return account_to_response(account)


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    account = (
        db.query(MT5Account)
        .filter(MT5Account.id == account_id, MT5Account.user_id == user_id)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    db.delete(account)
    db.commit()

    return {"message": "Account deleted successfully"}


@router.post("/{account_id}/connect")
async def connect_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    account = (
        db.query(MT5Account)
        .filter(MT5Account.id == account_id, MT5Account.user_id == user_id)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    if not account.instance_id:
        raise HTTPException(
            status_code=400, detail="No MT5 instance linked to this account"
        )

    try:
        password = encryption_service.decrypt(account.encrypted_password)

        account.connection_status = "connecting"
        db.commit()

        mt5 = MT5Service(account.instance_id)

        if not mt5.check_server():
            account.connection_status = "error"
            account.connection_error = "MT5 terminal not responding"
            db.commit()
            raise HTTPException(status_code=503, detail="MT5 terminal not responding")

        connected = mt5.connect(password, account.server)

        if connected:
            account.connection_status = "connected"
            account.last_connected = datetime.utcnow()
            account.connection_error = None
        else:
            account.connection_status = "error"
            account.connection_error = "Failed to connect to MT5"

        db.commit()

        return account_to_response(account)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Connection error: {e}")
        account.connection_status = "error"
        account.connection_error = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail="Failed to connect to MT5 account")


@router.post("/{account_id}/disconnect")
async def disconnect_account(
    account_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = user.id

    account = (
        db.query(MT5Account)
        .filter(MT5Account.id == account_id, MT5Account.user_id == user_id)
        .first()
    )

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        if account.instance_id:
            mt5 = MT5Service(account.instance_id)
            mt5.disconnect()
    except Exception as e:
        logger.warning(f"Disconnect warning: {e}")

    account.connection_status = "disconnected"
    account.last_disconnected = datetime.utcnow()
    db.commit()

    return account_to_response(account)
