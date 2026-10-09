"""FastAPI dependencies for authentication and role-based authorization."""
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import Role, User
from .security import decode_access_token

# tokenUrl powers the "Authorize" button in /docs (form login with email as username).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

ROLE_RANK = {Role.VIEWER: 0, Role.MANAGER: 1, Role.ADMIN: 2}


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Your session has expired or is invalid. Please sign in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized

    user = db.get(User, user_id)
    # Re-checking the database on every request means deactivating a user or changing
    # their password takes effect immediately, not when their token expires.
    if user is None or not user.is_active or payload.get("tv") != user.token_version:
        raise unauthorized
    return user


def require_role(minimum: Role):
    """Allow `minimum` and every role above it (VIEWER < MANAGER < ADMIN)."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if ROLE_RANK[user.role] < ROLE_RANK[minimum]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action needs the {minimum.value.lower()} role or higher.",
            )
        return user

    return dependency


require_viewer = get_current_user
require_manager = require_role(Role.MANAGER)
require_admin = require_role(Role.ADMIN)
