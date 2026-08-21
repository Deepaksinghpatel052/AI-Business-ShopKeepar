import secrets
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def generate_otp(length: int = 6) -> str:
    """Cryptographically secure numeric OTP, e.g. '048213'."""
    return "".join(str(secrets.randbelow(10)) for _ in range(length))


def hash_otp(code: str) -> str:
    return pwd_context.hash(code)


def verify_otp(code: str, code_hash: str) -> bool:
    return pwd_context.verify(code, code_hash)
