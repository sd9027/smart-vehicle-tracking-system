"""Password hashing (bcrypt), JWT creation/verification and a login-attempt limiter."""
import threading
import time
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, status

from .config import get_settings

settings = get_settings()

BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed hash, or a password longer than bcrypt's 72-byte limit.
        return False


# Used when the email does not exist, so a failed login takes the same time either way
# and attackers cannot discover which emails are registered by timing the response.
DUMMY_HASH = hash_password("timing-equaliser-not-a-real-account")


def create_access_token(user_id: int, role: str, token_version: int) -> tuple[str, int]:
    expires_in = settings.access_token_minutes * 60
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),  # PyJWT requires the subject to be a string
        "role": role,
        "tv": token_version,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError when the token is invalid, tampered with or expired."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],  # never accept the algorithm named in the token
        options={"require": ["exp", "sub"]},
    )


class LoginLimiter:
    """Locks an email for a few minutes after repeated failed logins.

    Stored in memory, so it resets when the server restarts and is per-process.
    That is fine for a single-server project; a production system would keep this
    in Redis or the database so every server shares it.
    """

    def __init__(self, max_attempts: int, lockout_seconds: int):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            until = self._locked_until.get(key)
            if until and until > time.monotonic():
                minutes = max(1, round((until - time.monotonic()) / 60))
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Too many failed sign-in attempts. Try again in about {minutes} minute(s).",
                )

    def fail(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._failures.get(key, []) if now - t < self.lockout_seconds]
            recent.append(now)
            self._failures[key] = recent
            if len(recent) >= self.max_attempts:
                self._locked_until[key] = now + self.lockout_seconds
                self._failures[key] = []

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


login_limiter = LoginLimiter(settings.login_max_attempts, settings.login_lockout_minutes * 60)
