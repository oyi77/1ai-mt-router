from pydantic import BaseModel, EmailStr
from typing import Optional


class UserCreate(BaseModel):
    username: str
    password: str
    email: Optional[EmailStr] = None


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class User(BaseModel):
    id: str
    username: str
    email: Optional[EmailStr] = None
    role: str = "admin"
