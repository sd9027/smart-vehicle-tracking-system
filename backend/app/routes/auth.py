"""Sign-in, current user and password change."""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User, utcnow
from ..schemas import LoginIn, PasswordChangeIn, TokenOut, UserOut
from ..security import DUMMY_HASH, create_access_token, hash_password, login_limiter, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "Incorrect email or password."


def _authenticate(db: Session, email: str, password: str) -> User:
    email = email.strip().lower()
    login_limiter.check(email)

    user = db.scalar(select(User).where(User.email == email))
    # Always run bcrypt, even for unknown emails, so response time leaks nothing.
    password_ok = verify_password(password, user.password_hash if user else DUMMY_HASH)

    # One generic message for unknown email, wrong password and deactivated account.
    if user is None or not password_ok or not user.is_active:
        login_limiter.fail(email)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID_LOGIN,
                            headers={"WWW-Authenticate": "Bearer"})

    login_limiter.success(email)
    user.last_login_at = utcnow()
    db.commit()
    return user


def _token_response(user: User) -> dict:
    token, expires_in = create_access_token(user.id, user.role.value, user.token_version)
    return {"access_token": token, "token_type": "bearer", "expires_in": expires_in,
            "user": UserOut.model_validate(user)}


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    """JSON login used by the React app."""
    return _token_response(_authenticate(db, body.email, body.password))


@router.post("/token", summary="Form login for the /docs Authorize button")
def token_for_swagger(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Swagger sends form fields; type your email into the 'username' box."""
    user = _authenticate(db, form.username, form.password)
    token, _ = create_access_token(user.id, user.role.value, user.token_version)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=TokenOut)
def change_password(body: PasswordChangeIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is incorrect.")
    if body.current_password == body.new_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password you have not just used.")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # signs out every other session using an old token
    db.commit()
    return _token_response(user)  # keep this browser signed in with a fresh token
