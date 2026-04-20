from fastapi import Header, HTTPException

from app.config import settings
from app.db import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.enable_admin_panel:
        raise HTTPException(status_code=404, detail="not_found")
    expected = settings.admin_token
    if expected is None:
        raise HTTPException(status_code=403, detail="admin_disabled")
    if x_admin_token != expected:
        raise HTTPException(status_code=403, detail="admin_forbidden")


def require_internal_access(x_admin_token: str | None = Header(default=None)) -> None:
    if settings.expose_internal_routes:
        return
    expected = settings.admin_token
    if expected is None or x_admin_token != expected:
        raise HTTPException(status_code=404, detail="not_found")
