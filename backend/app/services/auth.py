from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from fastapi import HTTPException, status
import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.identity import PhoneVerification
from app.models.user import User

VerificationSender = Callable[[str, str], None]
PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
PASSWORD_ITERATIONS = 310_000


def normalize_phone(phone: str) -> str:
    normalized = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not PHONE_PATTERN.fullmatch(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Phone number must use international E.164 format.",
        )
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _code_digest(user_id: str, code: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"{user_id}:{code}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_phone_verification(db: Session, user: User, sender: VerificationSender) -> None:
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge = db.scalar(select(PhoneVerification).where(PhoneVerification.user_id == user.id))
    if challenge is None:
        challenge = PhoneVerification(user_id=user.id, code_digest=_code_digest(user.id, code))
        db.add(challenge)
    else:
        challenge.code_digest = _code_digest(user.id, code)
        challenge.attempts = 0
        challenge.consumed_at = None
    challenge.expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.phone_verification_ttl_minutes
    )
    db.flush()
    if user.phone is None:
        raise ValueError("A phone number is required to send a verification code.")
    sender(user.phone, code)


def verify_phone_code(db: Session, user: User, code: str) -> bool:
    challenge = db.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.user_id == user.id)
        .with_for_update()
    )
    if challenge is None or challenge.consumed_at is not None:
        return False
    now = datetime.now(timezone.utc)
    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now or challenge.attempts >= settings.phone_verification_max_attempts:
        return False
    challenge.attempts += 1
    if not hmac.compare_digest(challenge.code_digest, _code_digest(user.id, code)):
        return False
    challenge.consumed_at = now
    user.phone_verified_at = now
    return True


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.id,
        "roles": user.roles or [],
        "permissions": user.permissions or [],
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(claims, settings.secret_key, algorithm=settings.jwt_algorithm)


def resolve_access_token(db: Session, token: str) -> User:
    try:
        claims = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        user_id = claims.get("sub")
        if not isinstance(user_id, str):
            raise InvalidTokenError("Token subject is invalid")
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.phone_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def send_verification_code(phone: str, code: str) -> None:
    account_sid = settings.twilio_account_sid
    auth_token = settings.twilio_auth_token
    from_number = settings.twilio_from_number
    if not account_sid or not auth_token or not from_number:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twilio phone verification delivery is not configured.",
        )

    credentials = b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    form_data = urlencode(
        {
            "To": phone,
            "From": from_number,
            "Body": f"Your {settings.app_name} verification code is {code}. It expires in {settings.phone_verification_ttl_minutes} minutes.",
        }
    ).encode("ascii")
    request = Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{quote(account_sid, safe='')}/Messages.json",
        data=form_data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            if not 200 <= response.status < 300:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Twilio could not deliver the phone verification message.",
                )
    except HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twilio could not deliver the phone verification message.",
        ) from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Twilio phone verification service is unavailable.",
        ) from exc
