from fastapi import HTTPException, status, Depends
from jose import jwt, JWTError
from models.shop_owner import ShopOwner
import os
from typing import Annotated
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
from utils.database import get_db
from sqlalchemy.orm import Session

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret")
ALGORITHM  = os.getenv("ALGORITHM", "HS256")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")
db_dependency = Annotated[Session, Depends(get_db)]

def verify_token(token: str, db) -> ShopOwner:
    """
    Token verify karo aur current user return karo.
    Har protected endpoint me is function ko use karo.
    """
    if not token.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token format must be: Bearer <token>"
        )

    raw_token = token.split(" ")[1]

    try:
        payload = jwt.decode(raw_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )

    user = db.query(ShopOwner).filter(ShopOwner.id == int(user_id)).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated"
        )

    return user

def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> ShopOwner:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = db.query(ShopOwner).filter(ShopOwner.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    return user