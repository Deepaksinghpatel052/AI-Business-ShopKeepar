from fastapi import FastAPI, HTTPException, status, Depends, Header, APIRouter
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker, Session
from typing import Annotated
from pydantic import BaseModel, EmailStr, field_validator
from passlib.context import CryptContext
from models.shop_owner import ShopOwner
import re, os
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from utils.auth import verify_token
from utils.database import get_db


load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

db_dependency = Annotated[Session, Depends(get_db)]

# ── Password hashing ──────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── FastAPI app ───────────────────────────────────────────────────────────────
router = APIRouter(prefix="/auth", tags=["Authentication"])


# ── Request schema ────────────────────────────────────────────────────────────

class SigninRequest(BaseModel):
    email: EmailStr
    password: str

class SignupRequest(BaseModel):
    name: str
    email: EmailStr
    username: str | None = None
    password: str
    phone: str | None = None
    shop_name: str | None = None

    @field_validator("name")
    def name_valid(cls, v):
        if len(v.strip()) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v.strip()

    @field_validator("password")
    def password_valid(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one number")
        return v

    @field_validator("username")
    def username_valid(cls, v):
        if v is None:
            return v
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v.lower()

# ── Response schema ───────────────────────────────────────────────────────────
class SigninResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    name: str
    email: str
    shop_name: str | None
    plan: str

class SignupResponse(BaseModel):
    id: int
    name: str
    email: str
    username: str | None
    shop_name: str | None
    plan: str
    message: str
    model_config = {"from_attributes": True}



@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: db_dependency):
    # Email duplicate check
    if db.query(ShopOwner).filter(ShopOwner.email == payload.email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists"
        )

    # Username duplicate check
    if payload.username:
        if db.query(ShopOwner).filter(ShopOwner.username == payload.username).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This username is already taken"
            )

    # Password hash karke save karo — plain password kabhi save nahi hota
    new_owner = ShopOwner(
        name=payload.name,
        email=payload.email,
        username=payload.username,
        password_hash=pwd_context.hash(payload.password),  # ← hashing yahan hoti hai
        phone=payload.phone,
        shop_name=payload.shop_name,
        auth_provider="local",
    )

    db.add(new_owner)
    db.commit()
    db.refresh(new_owner)

    return SignupResponse(
        id=new_owner.id,
        name=new_owner.name,
        email=new_owner.email,
        username=new_owner.username,
        shop_name=new_owner.shop_name,
        plan=new_owner.plan,
        message="Account created successfully"
    )

def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/signin", response_model=SigninResponse)
async def signin(payload: SigninRequest, db: db_dependency):
    # User dhundo
    user = db.query(ShopOwner).filter(ShopOwner.email == payload.email).first()

    # Email nahi mila ya password galat
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Account inactive hai
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated"
        )

    # Token generate karo
    token = create_access_token(user.id, user.email)

    # Last login update karo
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return SigninResponse(
        access_token=token,
        name=user.name,
        email=user.email,
        shop_name=user.shop_name,
        plan=user.plan,
    )


@router.post("/me")
async def get_my_profile(token: str, db: db_dependency):
    return verify_token(token, db)

@router.post("/token")
async def token_for_swagger(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: db_dependency = None,
):
    user = db.query(ShopOwner).filter(
        ShopOwner.email == form_data.username
    ).first()

    if not user or not pwd_context.verify(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    token = create_access_token(user.id, user.email)
    return {"access_token": token, "token_type": "bearer"}