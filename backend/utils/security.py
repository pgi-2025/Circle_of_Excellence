"""
Password hashing, coupon/certificate code generation, and small
cryptographic helpers shared across services.
"""
import secrets
import string
from werkzeug.security import generate_password_hash, check_password_hash


def hash_password(raw_password: str) -> str:
    return generate_password_hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return check_password_hash(password_hash, raw_password)


def random_code(length: int = 8, prefix: str = "") -> str:
    """Random uppercase alphanumeric code, e.g. for coupons/certificates."""
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}{body}" if prefix else body


def random_ambassador_code() -> str:
    """AMB + 5 digits, e.g. AMB48213."""
    digits = "".join(secrets.choice(string.digits) for _ in range(5))
    return f"AMB{digits}"
