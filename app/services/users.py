"""Users: login with lockout, admin management, self-service profile."""
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Role, User
from app.security import hash_password, password_problems, verify_password
from app.services.errors import NotFound, ServiceError

ROLE_DESCRIPTIONS = {
    "Admin": "Manages users, roles, integrations and settings",
    "PM": "Sees every project, dashboards and reports",
    "BA": "Creates tasks, logs hours, writes requirements with AI",
}
ROLE_NAMES = list(ROLE_DESCRIPTIONS)


def ensure_roles(db: Session) -> dict[str, Role]:
    existing = {r.name: r for r in db.scalars(select(Role))}
    for name, description in ROLE_DESCRIPTIONS.items():
        if name not in existing:
            existing[name] = Role(name=name, description=description)
            db.add(existing[name])
    db.flush()
    return existing


def get_user(db: Session, user_id: int) -> User:
    user = db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
    if user is None:
        raise NotFound("User not found.")
    return user


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))


def list_users(db: Session, include_inactive: bool = True) -> list[User]:
    query = select(User).options(selectinload(User.roles)).order_by(User.full_name)
    if not include_inactive:
        query = query.where(User.is_active.is_(True))
    return list(db.scalars(query))


def check_password(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise ServiceError("Password needs " + ", ".join(problems) + ".")


class LoginError(ServiceError):
    pass


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    return hash_password("not-a-real-password-1")


def authenticate(db: Session, email: str, password: str) -> User:
    """Return the user, or raise LoginError. Locks the account after too many failures."""
    user = get_by_email(db, email)
    now = datetime.now()
    generic = LoginError("Email or password is incorrect.")
    if user is None:
        verify_password(password, _dummy_hash())  # same timing as a real check
        raise generic
    if not user.is_active:
        raise LoginError("This account is deactivated. Contact an administrator.")
    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise LoginError(f"Account locked after too many failed attempts. Try again in {minutes} min.")
    if not verify_password(password, user.hashed_password):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= settings.MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=settings.LOCKOUT_MINUTES)
            user.failed_logins = 0
        db.commit()
        raise generic
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    db.commit()
    return user


def create_user(
    db: Session,
    email: str,
    full_name: str,
    password: str,
    role_names: list[str],
    job_title: str | None = None,
    weekly_capacity_hours: float = 40.0,
    must_change_password: bool = False,
) -> User:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ServiceError("Enter a valid email address.")
    if not full_name.strip():
        raise ServiceError("Full name is required.")
    if get_by_email(db, email):
        raise ServiceError("A user with that email already exists.")
    check_password(password)
    roles = ensure_roles(db)
    unknown = [r for r in role_names if r not in roles]
    if unknown or not role_names:
        raise ServiceError("Choose at least one valid role.")
    user = User(
        email=email,
        full_name=full_name.strip(),
        hashed_password=hash_password(password),
        job_title=job_title or None,
        weekly_capacity_hours=weekly_capacity_hours,
        must_change_password=must_change_password,
        is_active=True,
    )
    user.roles = [roles[r] for r in role_names]
    db.add(user)
    db.flush()
    return user


def update_user(
    db: Session,
    user: User,
    full_name: str,
    email: str,
    role_names: list[str],
    job_title: str | None,
    weekly_capacity_hours: float,
    actor: User,
) -> None:
    email = email.strip().lower()
    other = get_by_email(db, email)
    if other and other.id != user.id:
        raise ServiceError("Another user already has that email.")
    roles = ensure_roles(db)
    if not role_names or any(r not in roles for r in role_names):
        raise ServiceError("Choose at least one valid role.")
    if user.id == actor.id and "Admin" not in role_names:
        raise ServiceError("You cannot remove your own Admin role.")
    if not 0 < weekly_capacity_hours <= 80:
        raise ServiceError("Weekly capacity must be between 1 and 80 hours.")
    user.full_name = full_name.strip() or user.full_name
    user.email = email
    user.job_title = job_title or None
    user.weekly_capacity_hours = weekly_capacity_hours
    user.roles = [roles[r] for r in role_names]


def set_active(db: Session, user: User, active: bool, actor: User) -> None:
    if user.id == actor.id and not active:
        raise ServiceError("You cannot deactivate your own account.")
    if not active and user.is_admin:
        admins = [u for u in list_users(db, include_inactive=False) if u.is_admin]
        if len(admins) <= 1:
            raise ServiceError("At least one active admin must remain.")
    user.is_active = active


def reset_password(user: User, new_password: str) -> None:
    check_password(new_password)
    user.hashed_password = hash_password(new_password)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None


def unlock(user: User) -> None:
    user.failed_logins = 0
    user.locked_until = None


def change_own_password(user: User, current: str, new: str, confirm: str) -> None:
    if not verify_password(current, user.hashed_password):
        raise ServiceError("Current password is incorrect.")
    if new != confirm:
        raise ServiceError("New passwords do not match.")
    if current == new:
        raise ServiceError("Choose a password different from the current one.")
    check_password(new)
    user.hashed_password = hash_password(new)
    user.must_change_password = False


def bootstrap_admin(db: Session, email: str, password: str) -> User | None:
    """Create the first admin if there are no users yet (used at startup)."""
    ensure_roles(db)
    if db.scalar(select(func.count(User.id))):
        db.commit()
        return None
    user = create_user(db, email, "Administrator", password, ["Admin"])
    db.commit()
    return user
