from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.config import settings
from app.firestore_store import projects_collection, sessions_collection, users_collection
from app.registry import ensure_project_record
from app.panel_memory_core import panel_chat_fallback, store_panel_manual_memory
from app.schemas import ProjectSummary
from app.utils import utc_now_iso

router = APIRouter(tags=["public"])

SESSION_COOKIE_NAME = settings.session_cookie_name
SESSION_DURATION_SECONDS = settings.session_duration_seconds


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    iterations = 200_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_s, salt, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_s)
    except Exception:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations)
    return hmac.compare_digest(candidate.hex(), digest_hex)


class RegisterRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)
    project: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=200)


class SessionInfo(BaseModel):
    user_id: str
    issued_at: str
    expires_at: str


class AuthMeResponse(BaseModel):
    authenticated: bool
    user_id: Optional[str] = None
    expires_at: Optional[str] = None


class ProjectListResponse(BaseModel):
    projects: list[ProjectSummary]


class ProjectCreateRequest(BaseModel):
    project: str = Field(min_length=1, max_length=120)


class SessionPrincipal(BaseModel):
    user_id: str
    session_id: str
    expires_at: str


class PanelChatRequest(BaseModel):
    project: str = Field(min_length=1, max_length=120)
    book_id: str = Field(min_length=1, max_length=120, default="general")
    message: str = Field(min_length=1, max_length=4000)
    remember: bool = False


class PanelManualMemoryRequest(BaseModel):
    project: str = Field(min_length=1, max_length=120)
    book_id: str = Field(min_length=1, max_length=120, default="general")
    content: str = Field(min_length=1, max_length=4000)



def _make_session(user_id: str) -> tuple[SessionInfo, str]:
    now = _utc_now()
    expires = now + timedelta(seconds=SESSION_DURATION_SECONDS)
    session_id = secrets.token_urlsafe(32)
    sessions_collection.document(session_id).set(
        {
            "id": session_id,
            "user_id": user_id,
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "expires_at": _iso(expires),
            "status": "active",
        }
    )
    return SessionInfo(user_id=user_id, issued_at=_iso(now), expires_at=_iso(expires)), session_id


def _set_session_cookie(response: Response, session_id: str, expires_at: str) -> None:
    max_age = int((_parse_iso(expires_at) - _utc_now()).total_seconds())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=max(0, max_age),
        expires=max(0, max_age),
        path="/",
    )
    response.headers["Cache-Control"] = "no-store, max-age=0"


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.headers["Cache-Control"] = "no-store, max-age=0"


def _user_doc(user_id: str) -> dict | None:
    return users_collection.document(user_id).get().to_dict()


def _list_projects(user_id: str) -> list[ProjectSummary]:
    docs = projects_collection.where("user_id", "==", user_id).stream()
    projects = []
    for doc in docs:
        data = doc.to_dict() or {}
        projects.append(ProjectSummary(id=data.get("id", doc.id), project=data.get("project", ""), status=data.get("status", "active")))
    projects.sort(key=lambda item: item.project)
    return projects


def get_optional_session(request: Request) -> Optional[SessionPrincipal]:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        return None
    snapshot = sessions_collection.document(session_id).get().to_dict()
    if not snapshot:
        return None
    if snapshot.get("status") != "active":
        return None
    expires_at = snapshot.get("expires_at")
    if not expires_at:
        return None
    if _parse_iso(expires_at) <= _utc_now():
        sessions_collection.document(session_id).update({"status": "expired", "updated_at": utc_now_iso()})
        request.state.session_clear = True
        return None
    new_expires = _utc_now() + timedelta(seconds=SESSION_DURATION_SECONDS)
    new_expires_s = _iso(new_expires)
    sessions_collection.document(session_id).update({"updated_at": utc_now_iso(), "expires_at": new_expires_s})
    request.state.session_refresh = {"session_id": session_id, "expires_at": new_expires_s}
    return SessionPrincipal(user_id=snapshot["user_id"], session_id=session_id, expires_at=new_expires_s)


def require_session(request: Request) -> SessionPrincipal:
    principal = get_optional_session(request)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_required")
    return principal


def require_project_access(project: str, principal: SessionPrincipal = Depends(require_session)) -> SessionPrincipal:
    docs = projects_collection.where("user_id", "==", principal.user_id).where("project", "==", project).stream()
    if not list(docs):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="project_forbidden")
    return principal


@router.post("/auth/register", response_model=AuthMeResponse)
def register(payload: RegisterRequest, response: Response):
    existing = _user_doc(payload.user_id)
    if existing and existing.get("password_hash"):
        raise HTTPException(status_code=409, detail="user_exists")
    now = utc_now_iso()
    users_collection.document(payload.user_id).set(
        {
            "id": payload.user_id,
            "user_id": payload.user_id,
            "created_at": now,
            "updated_at": now,
            "memory_enabled": True,
            "panel_mode": settings.panel_mode,
            "password_hash": hash_password(payload.password),
        }
    )
    ensure_project_record(payload.user_id, payload.project)
    session, session_id = _make_session(payload.user_id)
    _set_session_cookie(response, session_id, session.expires_at)
    return AuthMeResponse(authenticated=True, user_id=payload.user_id, expires_at=session.expires_at)


@router.post("/auth/login", response_model=AuthMeResponse)
def login(payload: LoginRequest, response: Response):
    user = _user_doc(payload.user_id)
    if not user or not verify_password(payload.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="invalid_credentials")
    session, session_id = _make_session(payload.user_id)
    _set_session_cookie(response, session_id, session.expires_at)
    return AuthMeResponse(authenticated=True, user_id=payload.user_id, expires_at=session.expires_at)


@router.post("/auth/logout", response_model=AuthMeResponse)
def logout(request: Request, response: Response):
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        snapshot = sessions_collection.document(session_id).get().to_dict()
        if snapshot:
            sessions_collection.document(session_id).update({"status": "revoked", "updated_at": utc_now_iso()})
    _clear_session_cookie(response)
    return AuthMeResponse(authenticated=False)


@router.get("/auth/me", response_model=AuthMeResponse)
def auth_me(principal: Optional[SessionPrincipal] = Depends(get_optional_session)):
    if principal is None:
        return AuthMeResponse(authenticated=False)
    return AuthMeResponse(authenticated=True, user_id=principal.user_id, expires_at=principal.expires_at)


@router.get("/panel/projects", response_model=ProjectListResponse)
def panel_projects(principal: SessionPrincipal = Depends(require_session)):
    return ProjectListResponse(projects=_list_projects(principal.user_id))


@router.post("/panel/projects", response_model=ProjectListResponse)
def create_project(payload: ProjectCreateRequest, principal: SessionPrincipal = Depends(require_session)):
    ensure_project_record(principal.user_id, payload.project)
    return ProjectListResponse(projects=_list_projects(principal.user_id))




@router.post("/panel/memories/manual")
def panel_store_manual_memory(payload: PanelManualMemoryRequest, principal: SessionPrincipal = Depends(require_session)):
    docs = projects_collection.where("user_id", "==", principal.user_id).where("project", "==", payload.project).stream()
    if not list(docs):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="project_forbidden")
    core_memory = store_panel_manual_memory(
        user_id=principal.user_id,
        project=payload.project,
        book_id=payload.book_id,
        content=payload.content,
    )
    memory_id = (core_memory.get("fact") or core_memory.get("note") or {}).get("id")
    return {"status": "stored", "memory_id": memory_id, "legacy_memory_id": memory_id, "message": "Memoria guardada."}


@router.post("/panel/chat")
def panel_chat(payload: PanelChatRequest, principal: SessionPrincipal = Depends(require_session)):
    docs = projects_collection.where("user_id", "==", principal.user_id).where("project", "==", payload.project).stream()
    if not list(docs):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="project_forbidden")
    from app.chat import ChatRequest, chat

    request = ChatRequest(user_id=principal.user_id, project=payload.project, book_id=payload.book_id, message=payload.message, remember=payload.remember)
    response = chat(request)
    if payload.remember and "?" not in payload.message and "¿" not in payload.message:
        store_panel_manual_memory(
            user_id=principal.user_id,
            project=payload.project,
            book_id=payload.book_id,
            content=payload.message,
        )
    if response.get("mode") in {"clarification_required", "insufficient_memory"}:
        fallback = panel_chat_fallback(
            user_id=principal.user_id,
            project=payload.project,
            book_id=payload.book_id,
            message=payload.message,
        )
        if fallback is not None:
            return fallback
    return response
