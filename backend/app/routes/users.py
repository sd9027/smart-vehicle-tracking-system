"""User accounts, administrators only."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import Role, User
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import hash_password
from ..services.audit import transactional

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.name)).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    with transactional(db, admin, "CREATE_USER", "user") as tx:
        if db.scalar(select(User.id).where(User.email == body.email)):
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")
        user = User(name=body.name.strip(), email=body.email,
                    password_hash=hash_password(body.password), role=body.role)
        db.add(user)
        db.flush()
        tx.entity_id = user.id
        tx.message = f"Created {body.role.value.lower()} account"
        tx.details = {"email": body.email, "role": body.role.value}  # never the password
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    with transactional(db, admin, "UPDATE_USER", "user", user_id) as tx:
        user = db.get(User, user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
        if user.id == admin.id and (body.is_active is False or (body.role and body.role != Role.ADMIN)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "You cannot deactivate or demote your own account.")
        changes = {}
        if body.name is not None:
            user.name = body.name.strip()
            changes["name"] = user.name
        if body.role is not None and body.role != user.role:
            user.role = body.role
            user.token_version += 1  # old tokens carry the old role; force re-login
            changes["role"] = body.role.value
        if body.is_active is not None and body.is_active != user.is_active:
            user.is_active = body.is_active
            changes["is_active"] = body.is_active
        if body.password is not None:
            user.password_hash = hash_password(body.password)
            user.token_version += 1
            changes["password"] = "reset"
        tx.details = changes
        tx.message = "Updated user" if changes else "No changes"
    return user
