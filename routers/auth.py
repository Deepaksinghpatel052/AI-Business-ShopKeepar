from fastapi import FastAPI, HTTPException, status, Depends, Header, APIRouter
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker, Session
from typing import Annotated
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from passlib.context import CryptContext
from models.shop_owner import ShopOwner
import re, os, logging
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from utils.auth import verify_token, validate_password_strength, get_current_user
from utils.database import get_db
from utils.otp import generate_otp, hash_otp, verify_otp
from utils.email_service import send_verification_code_email

logger = logging.getLogger(__name__)

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
        return validate_password_strength(v)

    @field_validator("username")
    def username_valid(cls, v):
        if v is None:
            return v
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("Username can only contain letters, numbers, and underscores")
        return v.lower()

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    email: EmailStr
    verification_code: str = Field(min_length=6, max_length=6)
    new_password: str
    confirm_password: str

    @field_validator("verification_code")
    def code_valid(cls, v):
        if not v.isdigit():
            raise ValueError("Verification code must be a 6-digit number")
        return v

    @field_validator("new_password")
    def new_password_valid(cls, v):
        return validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self):
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

    @field_validator("new_password")
    def new_password_valid(cls, v):
        return validate_password_strength(v)

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
        logger.warning(f"Signup rejected — email already exists: {payload.email}")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists"
        )

    # Username duplicate check
    if payload.username:
        if db.query(ShopOwner).filter(ShopOwner.username == payload.username).first():
            logger.warning(f"Signup rejected — username already taken: {payload.username} ({payload.email})")
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

    logger.info(f"Signup successful — user_id={new_owner.id} email={new_owner.email}")

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
        logger.warning(f"Signin failed — incorrect email or password: {payload.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    # Account inactive hai
    if not user.is_active:
        logger.warning(f"Signin blocked — account deactivated: user_id={user.id} email={user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated"
        )

    # Token generate karo
    token = create_access_token(user.id, user.email)

    # Last login update karo
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    logger.info(f"Signin successful — user_id={user.id} email={user.email}")

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
        logger.warning(f"Token signin failed — incorrect email or password: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    token = create_access_token(user.id, user.email)
    logger.info(f"Token signin successful — user_id={user.id} email={user.email}")
    return {"access_token": token, "token_type": "bearer"}


# ── Forgot password ────────────────────────────────────────────────────────────
PASSWORD_RESET_CODE_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_CODE_EXPIRE_MINUTES", 10))
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = 60
PASSWORD_RESET_MAX_ATTEMPTS = 5


def _utcnow() -> datetime:
    # SQLite drops tzinfo on round-trip, so reset-code timestamps are stored/compared naive.
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/forgot-password/send-code", status_code=status.HTTP_200_OK)
async def send_password_reset_code(payload: ForgotPasswordRequest, db: db_dependency):
    """
    Email pe 6-digit verification code bhejo.
    User exist na kare tab bhi same generic response — email enumeration se bachne ke liye.
    """
    generic_response = {"message": "If an account with this email exists, a verification code has been sent."}

    user = db.query(ShopOwner).filter(ShopOwner.email == payload.email).first()
    if not user:
        logger.info(f"Password reset code requested for unknown email: {payload.email}")
        return generic_response

    now = _utcnow()
    if user.reset_code_last_sent_at and (now - user.reset_code_last_sent_at).total_seconds() < PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
        logger.warning(f"Password reset code resend blocked by cooldown — user_id={user.id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait a minute before requesting another code"
        )

    code = generate_otp()  # never logged — it's a secret

    try:
        send_verification_code_email(user.email, user.name, code, PASSWORD_RESET_CODE_EXPIRE_MINUTES)
    except Exception as e:
        logger.exception(f"Failed to send password reset email — user_id={user.id}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not send verification email: {str(e)}"
        )

    # Email bhejne ke baad hi DB update karo — send fail ho to code invalid hi rahe
    user.reset_code_hash = hash_otp(code)
    user.reset_code_expires_at = now + timedelta(minutes=PASSWORD_RESET_CODE_EXPIRE_MINUTES)
    user.reset_code_attempts = 0
    user.reset_code_last_sent_at = now
    db.commit()

    logger.info(f"Password reset code sent — user_id={user.id} email={user.email}")

    return generic_response


@router.post("/forgot-password/reset", status_code=status.HTTP_200_OK)
async def reset_password(payload: ResetPasswordRequest, db: db_dependency):
    """
    Verification code check karke password reset karo.
    """
    invalid_code_error = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid or expired verification code"
    )

    user = db.query(ShopOwner).filter(ShopOwner.email == payload.email).first()
    if not user or not user.reset_code_hash or not user.reset_code_expires_at:
        logger.warning(f"Password reset attempted with no pending code: {payload.email}")
        raise invalid_code_error

    if user.reset_code_attempts >= PASSWORD_RESET_MAX_ATTEMPTS:
        logger.warning(f"Password reset locked out — too many attempts: user_id={user.id}")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please request a new code."
        )

    if _utcnow() > user.reset_code_expires_at:
        logger.warning(f"Password reset attempted with expired code: user_id={user.id}")
        raise invalid_code_error

    if not verify_otp(payload.verification_code, user.reset_code_hash):
        user.reset_code_attempts += 1
        db.commit()
        logger.warning(f"Password reset attempted with wrong code: user_id={user.id} attempts={user.reset_code_attempts}")
        raise invalid_code_error

    # Code sahi hai — password update karo, code single-use hai to clear karo
    user.password_hash = pwd_context.hash(payload.new_password)
    user.reset_code_hash = None
    user.reset_code_expires_at = None
    user.reset_code_attempts = 0
    user.reset_code_last_sent_at = None
    db.commit()

    logger.info(f"Password reset successful — user_id={user.id} email={user.email}")

    return {"message": "Password reset successfully. Please sign in with your new password."}


# ── Change password (signed-in users) ────────────────────────────────────────
@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    payload: ChangePasswordRequest,
    db: db_dependency,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    Logged-in user apna password change kar sakta hai — old password verify karke.
    """
    if not pwd_context.verify(payload.old_password, current_user.password_hash):
        logger.warning(f"Change password failed — wrong old password: user_id={current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Old password is incorrect"
        )

    if payload.old_password == payload.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from the old password"
        )

    current_user.password_hash = pwd_context.hash(payload.new_password)
    db.commit()
    logger.info(f"Password changed — user_id={current_user.id} email={current_user.email}")

    return {"message": "Password changed successfully"}