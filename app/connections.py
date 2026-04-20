from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import SessionPrincipal, require_session
from app.config import settings
from app.connector_health import build_connector_self_check, build_maintenance_report
from app.dependencies import require_admin_token
from app.firestore_store import (
    audit_events_collection,
    chat_events_collection,
    llm_connections_collection,
    memory_indexes_collection,
    projects_collection,
    semantic_collection,
    support_events_collection,
    users_collection,
)
from app.llm_service import get_provider_catalog, get_user_llm_settings
from app.registry import ensure_project_record, ensure_user_record
from app.schemas import (
    AdminHealthResponse,
    AdminMetricsResponse,
    ConnectorSelfCheckResponse,
    MaintenanceVerifyResponse,
    ConnectionRequest,
    ConnectionStatusResponse,
    PanelBootstrapResponse,
    PanelMeResponse,
    ProjectSummary,
    ProviderCatalogResponse,
    ProviderMetadata,
)
from app.utils import new_memory_id, utc_now_iso

router = APIRouter(tags=["public"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

PUBLIC_SURFACE = [
    "/health",
    "/auth/register",
    "/auth/login",
    "/auth/logout",
    "/auth/me",
    "/chat",
    "/bridge/providers",
    "/bridge/{provider}/bootstrap",
    "/bridge/{provider}/manifest",
    "/bridge/{provider}/tool-call",
    "/connection/status",
    "/connection/providers",
    "/connection/connect",
    "/connection/disconnect",
    "/connection/pause",
    "/connection/resume",
    "/panel/me",
    "/panel/projects",
    "/panel/bootstrap",
    "/panel/chat",
]
PRIVATE_SURFACE = [
    "/memories",
    "/memories/search",
    "/memories/export",
    "/memories/audit",
    "/memories/seed-operational",
    "/admin/health",
    "/admin/metrics",
]


def _connection_response(user_id: str, request: Request | None = None) -> ConnectionStatusResponse:
    settings_obj = get_user_llm_settings(user_id)
    payload = settings_obj.model_dump()
    payload["status"] = payload.pop("connection_status")
    connection_doc = None
    for doc in llm_connections_collection.where("user_id", "==", user_id).stream():
        data = doc.to_dict() or {}
        if (data.get("provider") or "") == payload.get("provider") and data.get("status") in {"connected", "paused"}:
            connection_doc = data
            break
    if connection_doc:
        payload["bridge_token"] = connection_doc.get("bridge_token")
        if request is not None and connection_doc.get("bridge_token"):
            base = str(request.base_url).rstrip("/")
            token = connection_doc["bridge_token"]
            provider = connection_doc.get("provider") or payload.get("provider")
            payload["mcp_connector_url"] = f"{base}/mcp/sse?token={token}&provider={provider}"
            payload["mcp_sse_url"] = f"{base}/sse/?token={token}&provider={provider}"
            payload["mcp_http_url"] = f"{base}/mcp/rpc?token={token}&provider={provider}"
            payload["mcp_messages_url"] = f"{base}/sse/messages?token={token}&provider={provider}"
            payload["bridge_manifest_url"] = f"{base}/bridge/{provider}/manifest?token={token}"
            payload["bridge_tool_call_url"] = f"{base}/bridge/{provider}/tool-call?token={token}"
            payload["tool_calling_manifest_url"] = f"{base}/tool-calling/{provider}/manifest?token={token}"
            payload["tool_calling_call_url"] = f"{base}/tool-calling/{provider}/call?token={token}"
    return ConnectionStatusResponse(**payload)


def _provider_metadata() -> list[ProviderMetadata]:
    catalog = get_provider_catalog()
    return [
        ProviderMetadata(provider=name, **meta)
        for name, meta in sorted(catalog.items())
        if name != "mock"
    ]


def _project_summaries(user_id: str) -> list[ProjectSummary]:
    docs = projects_collection.where("user_id", "==", user_id).stream()
    projects = []
    for doc in docs:
        data = doc.to_dict() or {}
        projects.append(ProjectSummary(id=data.get("id", doc.id), project=data.get("project", ""), status=data.get("status", "active")))
    projects.sort(key=lambda item: item.project)
    return projects


def _audit(kind: str, details: dict) -> None:
    event_id = new_memory_id()
    audit_events_collection.document(event_id).set(
        {
            "id": event_id,
            "kind": kind,
            "details": details,
            "created_at": utc_now_iso(),
        }
    )


def _resolve_user(user_id: Optional[str], principal: SessionPrincipal) -> str:
    if user_id and user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="forbidden_user")
    return principal.user_id


@router.get("/connection/providers", response_model=ProviderCatalogResponse)
def connection_providers():
    return ProviderCatalogResponse(providers=_provider_metadata())


@router.get("/connection/status", response_model=ConnectionStatusResponse)
def connection_status(request: Request, user_id: str | None = None, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(user_id, principal)
    return _connection_response(resolved_user_id, request)


@router.post("/connection/connect", response_model=ConnectionStatusResponse)
def connect_memory(payload: ConnectionRequest, request: Request, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(payload.user_id, principal)
    provider = payload.provider.lower()
    catalog = get_provider_catalog()
    if provider not in catalog:
        raise HTTPException(status_code=400, detail="Proveedor no soportado")

    if payload.project:
        allowed = list(projects_collection.where("user_id", "==", resolved_user_id).where("project", "==", payload.project).stream())
        if not allowed:
            raise HTTPException(status_code=403, detail="project_forbidden")

    now = utc_now_iso()
    connection_id = f"{resolved_user_id}:{provider}"
    meta = catalog[provider]
    llm_connections_collection.document(connection_id).set(
        {
            "id": connection_id,
            "user_id": resolved_user_id,
            "provider": provider,
            "model_name": payload.model_name or meta["default_model"],
            "bridge_mode": payload.bridge_mode or meta["bridge_mode"],
            "status": "connected",
            "project": payload.project,
            "created_at": now,
            "updated_at": now,
            "requires_user_api_key": False,
            "bridge_token": secrets.token_urlsafe(24),
        }
    )
    ensure_user_record(resolved_user_id)
    if payload.project:
        ensure_project_record(resolved_user_id, payload.project)
    _audit("connection_connected", {"user_id": resolved_user_id, "provider": provider})
    return _connection_response(resolved_user_id, request)


@router.post("/connection/disconnect", response_model=ConnectionStatusResponse)
def disconnect_memory(request: Request, user_id: str | None = None, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(user_id, principal)
    docs = llm_connections_collection.where("user_id", "==", resolved_user_id).stream()
    found = False
    for doc in docs:
        llm_connections_collection.document(doc.id).update({"status": "disconnected", "updated_at": utc_now_iso()})
        found = True
    if not found:
        raise HTTPException(status_code=404, detail="Conexión no encontrada")
    _audit("connection_disconnected", {"user_id": resolved_user_id})
    return _connection_response(resolved_user_id, request)


@router.post("/connection/pause", response_model=ConnectionStatusResponse)
def pause_memory(request: Request, user_id: str | None = None, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(user_id, principal)
    docs = llm_connections_collection.where("user_id", "==", resolved_user_id).stream()
    updated = False
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("status") == "connected":
            llm_connections_collection.document(doc.id).update({"status": "paused", "updated_at": utc_now_iso()})
            updated = True
    if not updated:
        raise HTTPException(status_code=404, detail="Conexión activa no encontrada")
    _audit("connection_paused", {"user_id": resolved_user_id})
    return _connection_response(resolved_user_id, request)


@router.post("/connection/resume", response_model=ConnectionStatusResponse)
def resume_memory(request: Request, user_id: str | None = None, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(user_id, principal)
    docs = llm_connections_collection.where("user_id", "==", resolved_user_id).stream()
    updated = False
    for doc in docs:
        data = doc.to_dict() or {}
        if data.get("status") == "paused":
            llm_connections_collection.document(doc.id).update({"status": "connected", "updated_at": utc_now_iso()})
            updated = True
    if not updated:
        raise HTTPException(status_code=404, detail="Conexión pausada no encontrada")
    _audit("connection_resumed", {"user_id": resolved_user_id})
    return _connection_response(resolved_user_id, request)


@router.get("/panel/me", response_model=PanelMeResponse)
def panel_me(request: Request, user_id: str | None = None, principal: SessionPrincipal = Depends(require_session)):
    resolved_user_id = _resolve_user(user_id, principal)
    ensure_user_record(resolved_user_id)
    user_doc = users_collection.document(resolved_user_id).get().to_dict() or {}
    return PanelMeResponse(
        user_id=resolved_user_id,
        panel_mode=user_doc.get("panel_mode") or settings.panel_mode,
        memory_enabled=bool(user_doc.get("memory_enabled", True)),
        connection=_connection_response(resolved_user_id, request),
    )


@router.get("/panel/bootstrap", response_model=PanelBootstrapResponse)
def panel_bootstrap(request: Request, principal: SessionPrincipal = Depends(require_session)):
    ensure_user_record(principal.user_id)
    user_doc = users_collection.document(principal.user_id).get().to_dict() or {}
    me = PanelMeResponse(
        user_id=principal.user_id,
        panel_mode=user_doc.get("panel_mode") or settings.panel_mode,
        memory_enabled=bool(user_doc.get("memory_enabled", True)),
        connection=_connection_response(principal.user_id, request),
    )
    return PanelBootstrapResponse(me=me, projects=_project_summaries(principal.user_id), providers=_provider_metadata())


@admin_router.get("/health", response_model=AdminHealthResponse, dependencies=[Depends(require_admin_token)])
def admin_health():
    counts = {
        "users": len(list(users_collection.stream())),
        "projects": len(list(projects_collection.stream())),
        "semantic_memories": len(list(semantic_collection.stream())),
        "chat_events": len(list(chat_events_collection.stream())),
        "memory_indexes": len(list(memory_indexes_collection.stream())),
        "connections": len(list(llm_connections_collection.stream())),
    }
    return AdminHealthResponse(status="ok", panel_mode=settings.panel_mode, counts=counts)


@admin_router.get("/metrics", response_model=AdminMetricsResponse, dependencies=[Depends(require_admin_token)])
def admin_metrics(sample_user_id: str | None = Query(default=None)):
    counts = {
        "users": len(list(users_collection.stream())),
        "projects": len(list(projects_collection.stream())),
        "semantic_memories": len(list(semantic_collection.stream())),
        "chat_events": len(list(chat_events_collection.stream())),
        "memory_indexes": len(list(memory_indexes_collection.stream())),
        "connections": len(list(llm_connections_collection.stream())),
        "audit_events": len(list(audit_events_collection.stream())),
        "support_events": len(list(support_events_collection.stream())),
    }
    if sample_user_id:
        counts["sample_user_connections"] = len(
            list(llm_connections_collection.where("user_id", "==", sample_user_id).stream())
        )
    return AdminMetricsResponse(counts=counts, public_surface=PUBLIC_SURFACE, private_surface=PRIVATE_SURFACE)


@admin_router.get("/connectors/self-check", response_model=ConnectorSelfCheckResponse, dependencies=[Depends(require_admin_token)])
def admin_connectors_self_check(request: Request, user_id: str | None = Query(default=None)):
    payload = build_connector_self_check(str(request.base_url), user_id=user_id)
    return ConnectorSelfCheckResponse(**payload)


@admin_router.get("/maintenance/verify", response_model=MaintenanceVerifyResponse, dependencies=[Depends(require_admin_token)])
def admin_maintenance_verify():
    payload = build_maintenance_report()
    return MaintenanceVerifyResponse(**payload)
